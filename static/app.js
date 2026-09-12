const $=s=>document.querySelector(s);const $$=s=>Array.from(document.querySelectorAll(s));
const api=async(url,opt={})=>{const r=await fetch(url,opt);if(!r.ok){const raw=await r.text();let body={};try{body=JSON.parse(raw)}catch{body={detail:raw}}const message=body.message||'操作失败',detail=body.detail&&body.detail!==message?`：${body.detail}`:'',solution=body.solution?`\n建议：${body.solution}`:'';const error=new Error(`${message}${detail}${solution}`||'请求失败');error.code=body.code||`HTTP_${r.status}`;throw error}const ct=r.headers.get('content-type')||'';return ct.includes('json')?r.json():r.text()};
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const toast=t=>{const el=$('#toast');el.textContent=t;el.classList.remove('hidden');clearTimeout(window.__toastTimer);window.__toastTimer=setTimeout(()=>el.classList.add('hidden'),2600)};
async function safe(p){try{return await p}catch(e){toast(e.message||e);return null}}
const state={page:'算法列表',projects:[],project:null,datasets:[],datasetId:'default',images:[],labels:[],targets:[],jobs:[],models:[],algorithms:[],pending:[],testModels:[],inferenceEnvs:[],rec:null,localModels:[],activeImage:null,ann:null,activeLabel:0,activeBox:null,draw:null,imageFilter:'all',annHistory:[],annRedo:[],annZoom:1,annDirty:false,annAutoSaveTimer:null,logTimer:null};
const navs=['算法列表','训练资源','数据集','训练任务','测试发布'];
function closeModal(){$('#modal').classList.add('hidden');$('#modalBody').innerHTML='';$('#modal .modal-card').classList.remove('wide');state.activeImage=null} window.closeModal=closeModal;
function replaceModalContent(root,html){if(!root)return null;root.innerHTML=html;if(root.id==='modalBody')window.PostRenderNormalizationRuntime?.apply?.(root);return root} window.ModalContentRuntime=Object.freeze({replace:replaceModalContent});
function modal(title,body,wide=false){$('#modalTitle').textContent=title;window.ModalContentRuntime.replace($('#modalBody'),body);$('#modal .modal-card').classList.toggle('wide',!!wide);$('#modal').classList.remove('hidden');requestAnimationFrame(()=>{const first=document.querySelector('#modalBody input:not([disabled]),#modalBody select:not([disabled]),#modalBody textarea:not([disabled])');if(first)first.focus()})}
function splitName(s){return s==='val'?'试验集':s==='test'?'评测集':'训练集'}
function splitPill(s){return `<span class="pill ${s==='val'?'warn':s==='test'?'blue':'ok'}">${splitName(s)}</span>`}
async function ensureWorkspace(){let projects=await safe(api('/api/projects'))||[];if(!projects.length){const p=await safe(api('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'默认空间',description:'系统自动创建',labels:[]})}));if(p)projects=[p]}state.projects=projects;state.project=projects[0]||null}
async function loadAll(){await ensureWorkspace();await loadRelated();state.targets=(await safe(api(`/api/training_options${state.project?`?project_id=${state.project.id}`:''}`)))?.targets||[];state.inferenceEnvs=(await safe(api('/api/v16/inference_envs')))?.items||[];state.rec=await safe(api('/api/system/recommendation'));state.localModels=(await safe(api('/api/local_models')))?.items||[]}
async function loadRelated(){if(!state.project)return;const pid=state.project.id;const info=await safe(api(`/api/projects/${pid}`));if(info){state.project=info.project;state.jobs=info.jobs||[];state.models=info.models||[]}state.datasets=(await safe(api(`/api/projects/${pid}/datasets`)))?.items||[];if(!state.datasets.length){await safe(api(`/api/projects/${pid}/datasets`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'默认数据集',description:'',kind:'mixed'})}));state.datasets=(await safe(api(`/api/projects/${pid}/datasets`)))?.items||[]}if(!state.datasets.find(d=>d.id===state.datasetId))state.datasetId=state.datasets[0]?.id||'default';state.images=await safe(api(`/api/projects/${pid}/images?dataset_id=${state.datasetId}`))||[];state.labels=(await safe(api(`/api/v12/projects/${pid}/labels`)))?.items||[];state.algorithms=(await safe(api(`/api/v12/projects/${pid}/algorithms`)))?.items||[];state.pending=(await safe(api(`/api/v12/projects/${pid}/publish/pending`)))?.items||[];state.testModels=(await safe(api(`/api/v12/projects/${pid}/test_models`)))?.items||[]}
function statusName(s){return ({queued:'排队中',running:'训练中',done:'已完成',finished:'已完成',failed:'失败',stopped:'已停止'}[s]||s||'-')}
function render(){renderNav();renderTop();renderSummary();({算法列表:renderAlgorithms,训练资源:renderResources,数据集:renderDatasets,训练任务:renderTraining,测试发布:renderTest}[state.page]||renderAlgorithms)()}
function renderNav(){$('#nav').innerHTML=navs.map(n=>`<button class="nav-btn ${state.page===n?'active':''}" onclick="setPage('${n}')"><span>${n}</span><span>›</span></button>`).join('')}
function renderTop(){$('#crumb').textContent='畅联云算法训练';$('#title').textContent=state.page;$('#refreshBtn').onclick=async()=>{await loadAll();render();toast('已刷新')}}
function renderSummary(){
  const imgs=state.images.length;
  const ann=state.images.filter(i=>(i.box_count||0)>0).length;
  const boxes=state.images.reduce((a,b)=>a+(b.box_count||0),0);
  const ready=state.targets.filter(t=>t.status==='ready').length;
  const pending=state.pending.length;
  const done=state.jobs.filter(j=>['done','finished'].includes(j.status)).length;
  $('#summary').innerHTML=`<div class="stat"><div class="k">算法</div><div class="v">${state.algorithms.length}</div></div><div class="stat"><div class="k">训练资源</div><div class="v">${ready}</div></div><div class="stat"><div class="k">图片 / 已标注</div><div class="v">${imgs}/${ann}</div></div><div class="stat"><div class="k">标注框</div><div class="v">${boxes}</div></div><div class="stat"><div class="k">待发布 / 已训练</div><div class="v">${pending}/${done}</div></div>`;
}
function pid(){return state.project?.id}
async function reload(){await loadAll();render()}

function renderAlgorithms(){return window.renderAlgorithms423?.()}
window.delVersion=async(aid,vid)=>{if(!confirm('确认删除该版本？'))return;await safe(api(`/api/v12/projects/${pid()}/algorithms/${aid}/versions/${vid}`,{method:'DELETE'}));closeModal();const runtime=window.AlgorithmListRuntime;if(!runtime?.refresh){toast('算法列表刷新模块未加载，请刷新页面后重试');return}await runtime.refresh({render:true});toast('已删除版本')};

function renderResources(){
  const resourceCards = state.targets.map(t=>`<div class="res-card ${t.status==='ready'?'ready':'warn'}">
    <div class="res-main"><div class="res-icon">${t.framework==='paddle'?'桨':t.type==='server'?'服':'U'}</div><div><div class="item-title">${esc(t.name)}</div><div class="item-sub">${t.framework==='paddle'?'飞桨':t.framework==='ultralytics'?'Ultralytics':'未知'} · ${t.type==='server'?'训练服务器':'本机环境'} ${t.version?'· '+esc(t.version):''}</div></div></div>
    <div class="res-meta"><span class="pill ${t.status==='ready'?'ok':'warn'}">${t.status==='ready'?'可用':'待配置'}</span><span class="pill blue">${(t.algorithms||[]).length} 个算法</span><span class="pill">${(t.base_models||[]).length} 个权重</span></div>
  </div>`).join('');
  $('#view').innerHTML=`<div class="resource-layout"><section class="panel"><div class="panel-head"><div class="panel-title">接入训练资源</div><button class="btn small" onclick="loadAll().then(render)">刷新</button></div><div class="panel-body"><div class="resource-actions"><div class="quick-card"><div class="quick-title">本机 Ultralytics</div><div class="field"><label>安装目录</label><input id="uroot" class="input" placeholder="留空可自动检测"></div><div class="row"><button class="btn primary small" onclick="detectUltra()">检测并启用</button><button class="btn soft small" onclick="quickUltraDetect()">一键检测</button></div></div><div class="quick-card"><div class="quick-title">本机模型目录</div><div class="field"><label>模型目录</label><input id="scanRoot" class="input" placeholder="请选择或填写模型目录"></div><button class="btn small" onclick="scanModels()">扫描模型</button></div><div class="quick-card"><div class="quick-title">训练服务器</div><div class="field"><label>服务地址</label><input id="quickServerUrl" class="input" placeholder="http://192.168.1.10:8020"></div><button class="btn soft small" onclick="quickAddServer()">接入服务器</button></div></div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">已接入资源</div></div><div class="panel-body"><div class="resource-grid">${resourceCards||'<div class="empty">暂无资源。先检测本机 Ultralytics。</div>'}</div></div></section></div>`;
}
window.quickUltraDetect=()=>window.ResourceDiscoveryRuntime?.detectEnvironment({scope:'auto'})||toast('资源检测模块正在加载，请稍后重试');
window.detectUltra=()=>{const root=$('#uroot')?.value.trim()||'';return window.ResourceDiscoveryRuntime?.detectEnvironment(root?{scope:'fast',roots:[root]}:{scope:'auto'})||toast('资源检测模块正在加载，请稍后重试')};
window.scanModels=()=>{const root=$('#scanRoot')?.value.trim()||'';if(!root)return toast('请先填写要扫描的模型目录');return window.ResourceDiscoveryRuntime?.scanModels({scope:'directory',roots:[root]})||toast('资源检测模块正在加载，请稍后重试')};
window.addServer=()=>modal('新增训练服务器',`<div class="form"><div class="field"><label>服务器名称</label><input id="sname" class="input" placeholder="例如：GPU训练服务器"></div><div class="field"><label>服务地址</label><input id="surl" class="input" placeholder="http://192.168.1.10:8020"></div><button class="btn primary" onclick="saveServer()">保存</button></div>`);
window.quickAddServer=()=>{const url=$('#quickServerUrl').value.trim();if(!url)return toast('请输入服务器地址');modal('确认接入服务器',`<div class="form"><div class="field"><label>服务器名称</label><input id="sname" class="input" value="训练服务器"></div><div class="field"><label>服务地址</label><input id="surl" class="input" value="${esc(url)}"></div><button class="btn primary" onclick="saveServer()">保存</button></div>`)};
window.saveServer=async()=>{const action=window.NavigationStability?.action?.(state.page);const saved=await safe(api('/api/train_servers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$('#sname').value||'训练服务器',base_url:$('#surl').value})}));if(!saved||(action&&!action.isCurrent()))return;closeModal();const opts=await safe(api(`/api/training_options?project_id=${pid()}`));if(action&&!action.isCurrent())return;if(opts)state.targets=opts.targets||[];render();toast('已保存服务器')};

function renderDatasets(){return window.renderDatasets424?.()}

window.importData=()=>modal('导入已标注数据',`<div class="form"><div class="import-box"><div class="item-title">自动识别数据集格式</div><div class="item-sub">支持 YOLO、COCO、Pascal VOC 常见压缩包结构；导入后会自动转换成平台内部标注。</div></div><div class="field"><label>选择压缩包</label><input id="importFile" type="file" class="file" accept=".zip"></div><div id="importProgressWrap" class="progress-wrap hidden"><div class="progress-line"><span id="importProgressText">准备上传</span><b id="importProgressPercent">0%</b></div><div class="progress-bar"><i id="importProgressBar" style="width:0%"></i></div></div><div id="importResult"></div><div class="row end"><button class="btn soft" onclick="closeModal()">取消</button><button class="btn primary" onclick="doImportData()">开始导入</button></div></div>`,true);
window.doImportData=()=>{const f=$('#importFile').files[0];if(!f)return toast('请选择压缩包');const fd=new FormData();fd.append('file',f);const wrap=$('#importProgressWrap'),bar=$('#importProgressBar'),txt=$('#importProgressText'),pct=$('#importProgressPercent'),res=$('#importResult');wrap.classList.remove('hidden');bar.style.width='0%';pct.textContent='0%';txt.textContent='正在上传';res.innerHTML='';const xhr=new XMLHttpRequest();xhr.open('POST',`/api/v18/projects/${pid()}/datasets/${state.datasetId}/import`,true);xhr.upload.onprogress=e=>{if(e.lengthComputable){const p=Math.max(1,Math.round(e.loaded/e.total*100));bar.style.width=p+'%';pct.textContent=p+'%';if(p>=100)txt.textContent='上传完成，正在解析数据集';}};xhr.onerror=()=>{txt.textContent='导入失败';res.innerHTML='<div class="alert warn">网络或服务异常，请查看启动窗口日志。</div>'};xhr.onload=async()=>{let r=null;try{r=JSON.parse(xhr.responseText||'{}')}catch(e){}if(xhr.status>=200&&xhr.status<300&&r){bar.style.width='100%';pct.textContent='100%';txt.textContent='导入完成';const warns=(r.warnings||[]).map(x=>`<div class="alert warn">${esc(x)}</div>`).join('');res.innerHTML=`<div class="import-result"><div class="stat"><div class="k">格式</div><div class="v">${esc(r.detected_format||'-')}</div></div><div class="stat"><div class="k">图片</div><div class="v">${r.imported_images||0}</div></div><div class="stat"><div class="k">已标注</div><div class="v">${r.annotated_images||0}</div></div><div class="stat"><div class="k">标注框</div><div class="v">${r.boxes||0}</div></div></div>${warns}`;await window.refreshLabels414?.(false);if(state.page==='数据集')await window.reloadMaterialPage61?.();toast(`导入完成：${r.imported_images||0}图，${r.boxes||0}框`);}else{const msg=(r&&r.detail)||xhr.responseText||'导入失败';txt.textContent='导入失败';res.innerHTML=`<div class="alert warn">${esc(msg)}</div>`;}};xhr.send(fd);};

window.manageLabels=()=>{modal('标签管理',`<div class="panel-body"><div class="row"><button class="btn small soft" onclick="quickLabels('helmet')">安全帽模板</button><button class="btn small soft" onclick="quickLabels('fire')">烟火模板</button><button class="btn small primary" onclick="newLabel()">新增标签</button></div><div class="divider"></div><table class="table"><thead><tr><th>颜色</th><th>编码</th><th>显示名称</th><th>快捷键</th><th>操作</th></tr></thead><tbody>${state.labels.map(l=>`<tr><td><span class="dot" style="background:${l.color}"></span></td><td>${esc(l.code)}</td><td>${esc(l.display_name)}</td><td>${esc(l.hotkey||'')}</td><td><button class="btn small" onclick="editLabel(${l.class_id})">编辑</button><button class="btn small danger" onclick="delLabel(${l.class_id})">删除</button></td></tr>`).join('')||'<tr><td colspan="5">暂无标签</td></tr>'}</tbody></table></div>`)};
window.quickLabels=async t=>{const arr=t==='helmet'?[['person','人'],['helmet','安全帽'],['no_helmet','未戴安全帽']]:[['fire','明火'],['smoke','烟雾']];for(const [code,name] of arr){await safe(api(`/api/projects/${pid()}/labels`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:code,display_name:name})}))}await loadRelated();manageLabels()};
window.newLabel=()=>modal('新增标签',`<div class="form two"><div class="field"><label>编码</label><input id="lcode" class="input" placeholder="person"></div><div class="field"><label>名称</label><input id="lname" class="input" placeholder="人"></div></div><div class="divider"></div><button class="btn primary" onclick="saveNewLabel()">保存</button>`);
window.saveNewLabel=async()=>{await safe(api(`/api/projects/${pid()}/labels`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:$('#lcode').value,display_name:$('#lname').value})}));closeModal();await loadRelated();render();toast('已新增标签')};
window.editLabel=id=>{const l=state.labels.find(x=>x.class_id===id);modal('编辑标签',`<div class="form two"><div class="field"><label>编码</label><input id="lcode" class="input" value="${esc(l.code)}"></div><div class="field"><label>名称</label><input id="lname" class="input" value="${esc(l.display_name)}"></div><div class="field"><label>颜色</label><input id="lcolor" class="input" value="${esc(l.color)}"></div><div class="field"><label>快捷键</label><input id="lkey" class="input" value="${esc(l.hotkey)}"></div></div><div class="divider"></div><button class="btn primary" onclick="saveLabel(${id})">保存</button>`)};
window.saveLabel=async id=>{await safe(api(`/api/v12/projects/${pid()}/labels/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:$('#lcode').value,display_name:$('#lname').value,color:$('#lcolor').value,hotkey:$('#lkey').value})}));closeModal();await loadRelated();render();toast('已保存')};
window.delLabel=async id=>{if(!confirm('确认删除未使用标签？'))return;await safe(api(`/api/v12/projects/${pid()}/labels/${id}`,{method:'DELETE'}));await loadRelated();manageLabels()};

async function ensureLabels(){if(!state.labels.length){await quickAdd([['person','人'],['helmet','安全帽'],['no_helmet','未戴安全帽']]);await loadRelated()}}
async function quickAdd(arr){for(const [code,name] of arr){await safe(api(`/api/projects/${pid()}/labels`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:code,display_name:name})}))}}
async function ensureLabels(){if(!state.labels.length){await quickAdd([['person','人'],['helmet','安全帽'],['no_helmet','未戴安全帽']]);await loadRelated()}}
async function quickAdd(arr){for(const [code,name] of arr){await safe(api(`/api/projects/${pid()}/labels`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:code,display_name:name})}))}}
function imgIndex(){return state.images.findIndex(x=>x.id===state.activeImage?.id)}
async function openAnnotation(id){
  state.activeImage=state.images.find(x=>x.id===id);
  const resp=await safe(api(`/api/projects/${pid()}/annotations/${id}`));
  if(resp&&resp.image) state.activeImage=resp.image;
  state.ann=(resp&&resp.annotation)?resp.annotation:(resp||{boxes:[]});
  if(!Array.isArray(state.ann.boxes)) state.ann.boxes=[];
  await ensureLabels();
  state.activeLabel=state.labels[0]?.class_id||0;
  state.activeBox=null; state.annZoom=1; state.annDirty=false; state.annHistory=[]; state.annRedo=[];
  renderAnnotator();
} window.openAnnotation=openAnnotation;
function pushHistory(){state.annHistory.push(JSON.stringify(state.ann.boxes||[])); if(state.annHistory.length>50)state.annHistory.shift(); state.annRedo=[];}
function markDirty(){state.annDirty=true;const s=$('#annSaveState');if(s)s.textContent='未保存';clearTimeout(state.annAutoSaveTimer);state.annAutoSaveTimer=setTimeout(()=>saveAnn(true),900)}
function imageSize(){return {w:state.activeImage?.width||1,h:state.activeImage?.height||1}}
function renderAnnotator(){const img=state.activeImage;const idx=imgIndex();modal('图片标注',`<div class="ann-layout pro"><div class="ann-work"><div class="ann-toolbar"><button class="btn primary small" onclick="saveAnn(false)">保存</button><button class="btn small" onclick="prevImage()" ${idx<=0?'disabled':''}>上一张</button><button class="btn small" onclick="nextImage()" ${idx>=state.images.length-1?'disabled':''}>下一张</button><button class="btn small" onclick="undoAnn()">撤销</button><button class="btn small" onclick="redoAnn()">重做</button><button class="btn small danger" onclick="deleteActiveBox()">删框</button><span class="muted">${esc(img.filename)} · <b id="annSaveState">已保存</b></span><div class="ann-zoom"><button class="btn mini" onclick="zoomAnn(-0.1)">-</button><span id="zoomText">100%</span><button class="btn mini" onclick="zoomAnn(0.1)">+</button></div></div><div class="ann-canvas-wrap"><div id="annStage" class="ann-stage" style="transform:scale(${state.annZoom});transform-origin:top center"><img id="annImg" src="${img.url}"></div></div></div><aside class="side-panel ann-side"><div class="side-section"><div class="side-title">标签</div><div id="annLabels"></div><button class="btn small soft full" onclick="manageLabels()">管理标签</button></div><div class="side-section"><div class="side-title">框列表</div><div id="annBoxes"></div></div><div class="hint-card">快捷键：数字键切换标签，Delete 删除框，Ctrl+S 保存。</div></aside></div>`,true);const im=$('#annImg');const ready=()=>{drawBoxes();bindAnnotationEvents();};if(im.complete)ready();else im.onload=ready;renderAnnSide();}
function renderAnnSide(){const labels=state.labels;$('#annLabels').innerHTML=labels.map(l=>`<div class="label-row ${state.activeLabel===l.class_id?'active':''}" onclick="state.activeLabel=${l.class_id};renderAnnSide()"><span><span class="dot" style="background:${l.color}"></span>${esc(l.display_name)} <span class="muted">${esc(l.code)}</span></span><b>${esc(l.hotkey||'')}</b></div>`).join('');const boxes=state.ann.boxes||[];$('#annBoxes').innerHTML=boxes.map((b,i)=>{const l=labels.find(x=>x.class_id===b.class_id)||{};return`<div class="label-row ${state.activeBox===i?'active':''}" onclick="state.activeBox=${i};drawBoxes();renderAnnSide()"><span>${i+1}. ${esc(l.display_name||b.label)}</span><span>${Math.round(b.x2-b.x1)}×${Math.round(b.y2-b.y1)}</span></div>`}).join('')||'<div class="muted">暂无框。选择标签后，在图片上拖拽即可。</div>'}
function drawBoxes(){const st=$('#annStage');if(!st)return;st.querySelectorAll('.box,.drawBox').forEach(x=>x.remove());const size=imageSize(),labels=state.labels;function paint(b,i){const l=labels.find(x=>x.class_id===b.class_id)||{};const el=document.createElement('div');el.className='box '+(state.activeBox===i?'active':'');el.dataset.i=i;Object.assign(el.style,{left:(b.x1/size.w*100)+'%',top:(b.y1/size.h*100)+'%',width:((b.x2-b.x1)/size.w*100)+'%',height:((b.y2-b.y1)/size.h*100)+'%',borderColor:l.color||'#7c3aed'});el.innerHTML=`<div class="boxTag" style="background:${l.color||'#7c3aed'}">${esc(l.display_name||b.label)}</div>`;el.onclick=e=>{e.stopPropagation();state.activeBox=i;drawBoxes();renderAnnSide()};st.appendChild(el)};(state.ann.boxes||[]).forEach(paint)}
function bindAnnotationEvents(){const st=$('#annStage'),im=$('#annImg');if(!st||!im||st.dataset.bound==='1')return;st.dataset.bound='1';let start=null,temp=null;function pos(e){const r=im.getBoundingClientRect(),size=imageSize();return{x:Math.max(0,Math.min(size.w,(e.clientX-r.left)/Math.max(1,r.width)*size.w)),y:Math.max(0,Math.min(size.h,(e.clientY-r.top)/Math.max(1,r.height)*size.h))}}function tempBox(p){if(!start||!temp)return;const size=imageSize(),x1=Math.min(start.x,p.x),y1=Math.min(start.y,p.y),x2=Math.max(start.x,p.x),y2=Math.max(start.y,p.y);Object.assign(temp.style,{left:x1/size.w*100+'%',top:y1/size.h*100+'%',width:(x2-x1)/size.w*100+'%',height:(y2-y1)/size.h*100+'%'})}st.addEventListener('mousedown',e=>{if(e.button!==0||e.target.closest('.box'))return;e.preventDefault();const p=pos(e);start=p;temp=document.createElement('div');temp.className='drawBox';st.appendChild(temp);tempBox(p)});window.addEventListener('mousemove',e=>{if(!start||!temp)return;e.preventDefault();tempBox(pos(e))});window.addEventListener('mouseup',e=>{if(!start)return;e.preventDefault();const p=pos(e),x1=Math.min(start.x,p.x),y1=Math.min(start.y,p.y),x2=Math.max(start.x,p.x),y2=Math.max(start.y,p.y);if(temp)temp.remove();temp=null;if(x2-x1>5&&y2-y1>5){const l=state.labels.find(x=>x.class_id===state.activeLabel)||state.labels[0];if(l){pushHistory();state.ann.boxes.push({id:(crypto.randomUUID?crypto.randomUUID():String(Date.now())).slice(0,10),class_id:l.class_id,label:l.code,x1:Math.round(x1),y1:Math.round(y1),x2:Math.round(x2),y2:Math.round(y2)});state.activeBox=state.ann.boxes.length-1;markDirty()}}start=null;drawBoxes();renderAnnSide()})}
window.saveAnn=async(silent=false)=>{const r=await safe(api(`/api/projects/${pid()}/annotations/${state.activeImage.id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({boxes:state.ann.boxes})}));if(r&&r.annotation){state.ann=r.annotation;if(!Array.isArray(state.ann.boxes))state.ann.boxes=[];}state.annDirty=false;const s=$('#annSaveState');if(s)s.textContent=`已保存（${state.ann.boxes.length}框）`;await loadRelated();drawBoxes();renderAnnSide();if(!silent)toast(`标注已保存：${state.ann.boxes.length}个框`)};
window.deleteActiveBox=()=>{if(state.activeBox==null)return toast('请选择一个框');pushHistory();state.ann.boxes.splice(state.activeBox,1);state.activeBox=null;markDirty();drawBoxes();renderAnnSide()};
window.undoAnn=()=>{if(!state.annHistory.length)return;state.annRedo.push(JSON.stringify(state.ann.boxes||[]));state.ann.boxes=JSON.parse(state.annHistory.pop());state.activeBox=null;markDirty();drawBoxes();renderAnnSide()};
window.redoAnn=()=>{if(!state.annRedo.length)return;pushHistory();state.ann.boxes=JSON.parse(state.annRedo.pop());state.activeBox=null;markDirty();drawBoxes();renderAnnSide()};
window.zoomAnn=d=>{state.annZoom=Math.max(.5,Math.min(2.2,(state.annZoom||1)+d));const st=$('#annStage');if(st)st.style.transform=`scale(${state.annZoom})`;const z=$('#zoomText');if(z)z.textContent=Math.round(state.annZoom*100)+'%'};
window.prevImage=async()=>{const i=imgIndex();if(i>0){if(state.annDirty)await saveAnn(true);openAnnotation(state.images[i-1].id)}};
window.nextImage=async()=>{const i=imgIndex();if(i>=0&&i<state.images.length-1){if(state.annDirty)await saveAnn(true);openAnnotation(state.images[i+1].id)}};
document.addEventListener('keydown',e=>{if(!state.activeImage)return;if(e.key>='1'&&e.key<='9'){const hit=state.labels.find(l=>l.hotkey===e.key)||state.labels[+e.key-1];if(hit){state.activeLabel=hit.class_id;renderAnnSide();toast(`当前标签：${hit.display_name}`)}}if(e.key==='Delete')deleteActiveBox();if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();saveAnn(false)}if(e.key==='ArrowLeft')prevImage();if(e.key==='ArrowRight')nextImage()});

function renderTraining(){const rec=state.rec?.recommendation||{};$('#view').innerHTML=`<div class="grid2"><section class="panel"><div class="panel-head"><div class="panel-title">创建训练任务</div><span class="pill ok">推荐 ${esc(rec.model||'yolo11n.pt')} / ${esc(rec.device||'cpu')}</span></div><div class="panel-body"><div class="form two"><div class="field"><label>训练数据集</label><select class="select" id="trainDataset">${state.datasets.map(d=>`<option value="${d.id}" ${d.id===state.datasetId?'selected':''}>${esc(d.name)}（${d.images}图）</option>`).join('')}</select></div><div class="field"><label>训练资源</label><select class="select" id="target" onchange="fillTrain()">${state.targets.map(t=>`<option value="${t.id}">${esc(t.name)} / ${t.type==='server'?'服务器':'本机'}</option>`).join('')}</select></div><div class="field"><label>训练算法</label><select class="select" id="alg" onchange="applyAlg()"></select></div><div class="field"><label>基础模型权重</label><select class="select" id="model"></select></div><div class="field"><label>训练轮次</label><input class="input" id="epochs" value="${rec.epochs||20}"></div><div class="field"><label>图片尺寸</label><input class="input" id="imgsz" value="${rec.imgsz||640}"></div><div class="field"><label>批大小</label><input class="input" id="batch" value="${rec.batch||4}"></div><div class="field"><label>训练设备</label><input class="input" id="device" value="${rec.device||'cpu'}"></div></div><div class="divider"></div><button class="btn primary" onclick="startTrain()">开始训练</button></div></section><section class="panel"><div class="panel-head"><div class="panel-title">任务列表</div><button class="btn small" onclick="loadAll().then(render)">刷新</button></div><div class="panel-body"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>数据集</th><th>操作</th></tr></thead><tbody>${state.jobs.map(j=>`<tr><td>${esc(j.algorithm_name||j.id)}</td><td><span class="pill ${j.status==='done'||j.status==='finished'?'ok':j.status==='failed'?'err':'warn'}">${statusName(j.status)}</span></td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td><div class="row"><button class="btn small" onclick="showLog('${j.id}')">日志</button><button class="btn small danger" onclick="stopJob('${j.id}')">停止</button><button class="btn small danger" onclick="deleteJob('${j.id}')">删除</button></div></td></tr>`).join('')||'<tr><td colspan="4">暂无训练任务</td></tr>'}</tbody></table></div></section></div><section class="panel"><div class="panel-head"><div class="panel-title">训练日志</div></div><div class="panel-body"><pre id="log" class="log">选择任务查看日志</pre></div></section>`;fillTrain()}
function curTarget(){return state.targets.find(t=>t.id===$('#target')?.value)||state.targets[0]}
window.fillTrain=()=>{const t=curTarget(),a=$('#alg'),m=$('#model');if(!t||!a||!m){return}a.innerHTML=(t.algorithms||[]).map(x=>`<option value="${x.key}">${esc(x.name)}</option>`).join('')||'<option value="">无可用算法</option>';m.innerHTML=(t.base_models||[]).map(x=>`<option value="${esc(x.value||'')}">${esc(x.label||x.value||'默认权重')}</option>`).join('')||'<option value="">默认权重</option>';applyAlg()};
window.applyAlg=()=>{const t=curTarget();const alg=(t?.algorithms||[]).find(x=>x.key===$('#alg')?.value);if(!alg)return;$('#epochs').value=alg.default_epochs||$('#epochs').value;$('#imgsz').value=alg.default_imgsz||$('#imgsz').value;$('#batch').value=alg.default_batch||$('#batch').value;const m=$('#model');const hit=[...m.options].find(o=>(o.value||o.textContent).toLowerCase().includes(String(alg.base_model||'').toLowerCase()));if(hit)m.value=hit.value};
window.showLog=async id=>{$('#log').textContent=await safe(api(`/api/projects/${pid()}/jobs/${id}/log`))||'暂无日志'};
window.stopJob=async id=>{await safe(api(`/api/projects/${pid()}/jobs/${id}/stop`,{method:'POST'}));await reload();toast('已请求停止')};
window.deleteJob=async id=>{if(!confirm('确认删除训练任务？'))return;await safe(api(`/api/v12/projects/${pid()}/jobs/${id}`,{method:'DELETE'}));await reload();toast('已删除')};

function renderTest(){
  const envOptions=(state.inferenceEnvs||[]).map(e=>`<option value="${esc(e.id)}" data-fw="${esc(e.framework)}" ${e.status==='ready'?'':'disabled'}>${esc(e.name)} / ${e.framework==='paddle'?'飞桨':e.framework==='ultralytics'?'Ultralytics':'服务器'}${e.status==='ready'?'':'（不可用）'}</option>`).join('');
  $('#view').innerHTML=`<div class="grid2"><section class="panel"><div class="panel-head"><div class="panel-title">模型测试</div><button class="btn small" onclick="loadAll().then(render)">刷新环境</button></div><div class="panel-body"><div class="form"><div class="field"><label>测试环境</label><select class="select" id="inferEnv" onchange="syncTestModelByEnv()">${envOptions||'<option value="">暂无可用测试环境</option>'}</select></div><div class="field"><label>测试模型</label><select class="select" id="testModel">${state.testModels.map((m,i)=>`<option value="${i}" data-fw="${esc(m.framework||'ultralytics')}">${esc(m.label)}</option>`).join('')}</select></div><div class="field"><label>置信度</label><input id="conf" class="input" value="0.25"></div><div class="field"><label>测试图片</label><input id="predFile" type="file" accept="image/*" class="file"></div><button class="btn primary" onclick="predict()">开始测试</button><div id="predResult"></div></div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">待发布模型</div></div><div class="panel-body"><table class="table"><thead><tr><th>模型</th><th>大小</th><th>操作</th></tr></thead><tbody>${state.pending.map(m=>`<tr><td>${esc(m.name)}</td><td>${m.size_mb}MB</td><td><button class="btn small primary" onclick="assignVersion('${esc(m.name)}')">归属算法</button></td></tr>`).join('')||'<tr><td colspan="3">暂无待发布模型</td></tr>'}</tbody></table></div></section></div><section class="panel"><div class="panel-head"><div class="panel-title">测试环境状态</div></div><div class="panel-body"><div class="card-list">${(state.inferenceEnvs||[]).map(e=>`<div class="item"><div><div class="item-title">${esc(e.name)}</div><div class="item-sub">${esc(e.python_path||e.base_url||'')} · ${esc(e.note||'')}</div></div><span class="pill ${e.status==='ready'?'ok':e.status==='warning'?'warn':'err'}">${e.status==='ready'?'可用':e.status==='warning'?'需确认':'不可用'}</span></div>`).join('')||'<div class="empty">暂无测试环境，请先到训练资源里检测 Ultralytics 或配置飞桨。</div>'}</div></div></section>`;
  syncTestModelByEnv();
}
window.syncTestModelByEnv=()=>{
  const envSel=$('#inferEnv'), modelSel=$('#testModel'); if(!envSel||!modelSel)return;
  const fw=envSel.selectedOptions[0]?.dataset?.fw||'';
  [...modelSel.options].forEach(o=>{const ok=!fw||!o.dataset.fw||o.dataset.fw===fw||(fw==='ultralytics'&&o.dataset.fw==='');o.hidden=!ok;o.disabled=!ok});
  const first=[...modelSel.options].find(o=>!o.disabled); if(first)modelSel.value=first.value;
};
window.predict=async()=>{
  const f=$('#predFile').files[0];if(!f)return toast('请选择图片');
  const m=state.testModels[+$('#testModel').value];if(!m)return toast('暂无可测试模型');
  const env=$('#inferEnv'); const selected=env?.selectedOptions?.[0]; if(!selected||selected.disabled)return toast('请选择可用测试环境');
  const fw=selected.dataset.fw||m.framework||'ultralytics';
  const fd=new FormData();fd.append('conf',$('#conf').value);fd.append('file',f);fd.append('inference_env_id',env.value);fd.append('inference_framework',fw);
  if(m.framework==='paddle'||m.model_source==='paddle_builtin'||m.model_source==='paddle_model'){
    fd.append('model_source',m.model_source||'paddle_builtin');fd.append('model_name',m.model_name||'PP-YOLOE-S_human');
  }else if(m.algorithm_id){fd.append('algorithm_id',m.algorithm_id);fd.append('version_id',m.version_id)}
  else if(m.model_source==='local'){fd.append('model_source','local');fd.append('local_path',m.path);fd.append('model_name',m.path)}
  else{fd.append('model_source','project');fd.append('model_name',m.model_name)}
  const r=await safe(api(`/api/v12/projects/${pid()}/predict`,{method:'POST',body:fd}));
  if(r)$('#predResult').innerHTML=`<div class="divider"></div><div class="row"><span class="pill ok">耗时 ${r.elapsed_ms} ms</span><span class="pill blue">${(r.detections||[]).length} 个结果</span><span class="pill">${esc(r.engine||'')}</span></div><div class="item-sub">测试环境：${esc(r.python_path||'')}</div><div class="divider"></div><img class="result-img" src="${r.image_url}"><div class="divider"></div><table class="table"><thead><tr><th>标签</th><th>置信度</th><th>坐标</th></tr></thead><tbody>${(r.detections||[]).map(d=>`<tr><td>${esc(d.label)}</td><td>${d.confidence}</td><td>${d.x1},${d.y1},${d.x2},${d.y2}</td></tr>`).join('')||'<tr><td colspan="3">无结果</td></tr>'}</tbody></table>`
};
window.assignVersion=name=>{if(!state.algorithms.length)return toast('请先在算法列表创建算法');modal('归属到算法',`<div class="form"><div class="field"><label>模型</label><input class="input" value="${esc(name)}" disabled></div><div class="field"><label>算法</label><select id="algoSel" class="select">${state.algorithms.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></div><div class="field"><label>版本名称</label><input id="verName" class="input" placeholder="例如：V1.0"></div><div class="field"><label>备注</label><textarea id="verRemark"></textarea></div><button class="btn primary" onclick="saveAssign('${esc(name)}')">确认归属</button></div>`)};
window.saveAssign=async name=>{await safe(api(`/api/v12/projects/${pid()}/algorithms/${$('#algoSel').value}/versions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:name,model_source:'project',version_name:$('#verName').value,remark:$('#verRemark').value})}));closeModal();await reload();toast('已归属到算法')};

async function init(){await loadAll();render()} window.__clInit=init;

// -----------------------------
// v19 导入任务：先选择图片，再后台解析，右下角查看进度
// -----------------------------
state.importJobs = [];
state.activeImportJob = null;
state.importPollTimer = null;

function ensureImportDock(){
  if(document.getElementById('importDock'))return;
  const dock=document.createElement('div');
  dock.id='importDock';
  dock.className='import-dock hidden';
  dock.innerHTML='<button class="import-dock-btn" onclick="openImportDock()"><span class="dot-live"></span><b id="importDockTitle">导入任务</b><small id="importDockText">暂无任务</small></button>';
  document.body.appendChild(dock);
}
async function loadImportJobs(){
  if(!pid())return [];
  const r=await safe(api(`/api/v19/projects/${pid()}/import/jobs`));
  state.importJobs=(r&&r.items)||[];
  updateImportDock();
  return state.importJobs;
}
function updateImportDock(){
  ensureImportDock();
  const dock=$('#importDock');
  const jobs=state.importJobs||[];
  if(!jobs.length){dock.classList.add('hidden');return;}
  dock.classList.remove('hidden');
  const running=jobs.find(j=>j.status==='running');
  const latest=running||jobs[0];
  const title=$('#importDockTitle'), txt=$('#importDockText');
  const p=Math.round(latest.progress||0);
  title.textContent=running?'正在解析数据集':'导入任务';
  txt.textContent=`${latest.stage||statusImportName(latest.status)} · ${p}%`;
  dock.classList.toggle('running',!!running);
}
function statusImportName(s){return ({selecting:'待选择',running:'解析中',done:'已完成',failed:'失败'}[s]||s||'-')}
function startImportPolling(){
  ensureImportDock();
  if(state.importPollTimer)return;
  state.importPollTimer=setInterval(async()=>{
    await loadImportJobs();
    const hasRunning=(state.importJobs||[]).some(j=>j.status==='running');
    if(!hasRunning && state.importPollTimer){clearInterval(state.importPollTimer);state.importPollTimer=null;}
  },1200);
}
window.openImportDock=async()=>{
  await loadImportJobs();
  modal('后台导入任务', renderImportJobsPanel(), true);
};
function renderImportJobsPanel(){
  const jobs=state.importJobs||[];
  return `<div class="import-jobs">${jobs.map(j=>renderImportJobCard(j)).join('')||'<div class="empty">暂无导入任务</div>'}</div><div class="row end"><button class="btn soft" onclick="closeModal()">关闭</button><button class="btn" onclick="loadImportJobs().then(()=>window.ModalContentRuntime.replace(document.getElementById('modalBody'),renderImportJobsPanel()))">刷新</button></div>`;
}
function renderImportJobCard(j){
  const r=j.report||{};
  const warns=(r.warnings||[]).map(x=>`<div class="alert warn">${esc(x)}</div>`).join('');
  const err=j.error?`<div class="alert warn">${esc(j.error)}</div>`:'';
  return `<div class="import-job-card">
    <div class="between row"><div><div class="item-title">${esc(j.file_name)}</div><div class="item-sub">${esc(j.stage||'')} · ${esc(j.message||'')}</div></div><span class="pill ${j.status==='done'?'ok':j.status==='failed'?'err':'warn'}">${statusImportName(j.status)}</span></div>
    <div class="progress-wrap"><div class="progress-line"><span>${esc(j.stage||'-')}</span><b>${Math.round(j.progress||0)}%</b></div><div class="progress-bar"><i style="width:${Math.round(j.progress||0)}%"></i></div></div>
    <div class="import-result"><div class="stat"><div class="k">候选图片</div><div class="v">${j.image_count||0}</div></div><div class="stat"><div class="k">已导入</div><div class="v">${r.imported_images||0}</div></div><div class="stat"><div class="k">已标注</div><div class="v">${r.annotated_images||0}</div></div><div class="stat"><div class="k">标注框</div><div class="v">${r.boxes||0}</div></div></div>
    ${err}${warns}
    <div class="row end"><button class="btn small danger" onclick="deleteImportJob('${j.id}')">删除记录</button></div>
  </div>`;
}
window.deleteImportJob=async(id)=>{if(!confirm('确认删除这个导入任务记录？'))return;await safe(api(`/api/v19/projects/${pid()}/import/jobs/${id}`,{method:'DELETE'}));await loadImportJobs();if(!$('#modal').classList.contains('hidden'))window.ModalContentRuntime.replace($('#modalBody'),renderImportJobsPanel());};

// 覆盖 v18 导入弹窗
window.importData=()=>modal('导入已标注数据',`<div class="form"><div class="import-box"><div class="item-title">先上传压缩包，再选择要解析的图片</div><div class="item-sub">适合网上下载的大数据集。上传后不会立即全部解析，可勾选部分图片先试导入；解析任务可缩放到后台，右下角查看进度。</div></div><div class="field"><label>选择压缩包</label><input id="importFile" type="file" class="file" accept=".zip"></div><div id="importProgressWrap" class="progress-wrap hidden"><div class="progress-line"><span id="importProgressText">准备上传</span><b id="importProgressPercent">0%</b></div><div class="progress-bar"><i id="importProgressBar" style="width:0%"></i></div></div><div id="importResult"></div><div class="row end"><button class="btn soft" onclick="closeModal()">取消</button><button class="btn primary" onclick="doImportUploadV19()">上传并扫描</button></div></div>`,true);
window.doImportUploadV19=()=>{
  const f=$('#importFile').files[0];if(!f)return toast('请选择压缩包');
  const fd=new FormData();fd.append('file',f);
  const wrap=$('#importProgressWrap'),bar=$('#importProgressBar'),txt=$('#importProgressText'),pct=$('#importProgressPercent'),res=$('#importResult');
  wrap.classList.remove('hidden');bar.style.width='0%';pct.textContent='0%';txt.textContent='正在上传';res.innerHTML='';
  const xhr=new XMLHttpRequest();
  xhr.open('POST',`/api/v19/projects/${pid()}/datasets/${state.datasetId}/import/jobs`,true);
  xhr.upload.onprogress=e=>{if(e.lengthComputable){const p=Math.max(1,Math.round(e.loaded/e.total*100));bar.style.width=p+'%';pct.textContent=p+'%';if(p>=100)txt.textContent='上传完成，正在扫描图片列表';}};
  xhr.onerror=()=>{txt.textContent='上传失败';res.innerHTML='<div class="alert warn">网络或服务异常，请查看启动窗口日志。</div>'};
  xhr.onload=async()=>{let r=null;try{r=JSON.parse(xhr.responseText||'{}')}catch(e){}if(xhr.status>=200&&xhr.status<300&&r){state.activeImportJob=r;bar.style.width='100%';pct.textContent='100%';txt.textContent='扫描完成';await loadImportJobs();res.innerHTML=renderImportPicker(r);toast(`扫描完成：${r.image_count||0} 张候选图片`);}else{const msg=(r&&r.detail)||xhr.responseText||'上传或扫描失败';txt.textContent='失败';res.innerHTML=`<div class="alert warn">${esc(msg)}</div>`;}};
  xhr.send(fd);
};
function renderImportPicker(job){
  const imgs=job.images||[];
  const shown=imgs.slice(0,500);
  const more=imgs.length>shown.length?`<div class="alert warn">当前只显示前 ${shown.length} 张，点击“解析全部”会解析压缩包内全部 ${imgs.length} 张图片。</div>`:'';
  return `<div class="divider"></div><div class="import-result"><div class="stat"><div class="k">候选格式</div><div class="v">${esc((job.format_hints||[]).join('/'))}</div></div><div class="stat"><div class="k">图片数</div><div class="v">${job.image_count||0}</div></div><div class="stat"><div class="k">文件数</div><div class="v">${job.file_count||0}</div></div><div class="stat"><div class="k">解压后</div><div class="v">${job.uncompressed_size_mb||0}MB</div></div></div>${more}<div class="row between"><div class="item-sub">可先勾选少量图片试解析，确认标签和框正常后再导入全部。</div><div class="row"><button class="btn small" onclick="toggleImportChecks(true)">全选当前页</button><button class="btn small" onclick="toggleImportChecks(false)">清空</button></div></div><div class="import-select-list">${shown.map((im,i)=>`<label class="import-select-row"><input type="checkbox" class="impChk" value="${esc(im.path)}" ${i<20?'checked':''}><span>${esc(im.name)}</span><em>${esc(splitName(im.split))}</em><small>${esc(im.path)}</small></label>`).join('')}</div><div class="row end"><button class="btn soft" onclick="closeModal()">稍后处理</button><button class="btn" onclick="startImportJobV19(false)">解析勾选图片</button><button class="btn primary" onclick="startImportJobV19(true)">解析全部并缩到后台</button></div>`;
}
window.toggleImportChecks=(checked)=>{$$('.impChk').forEach(x=>x.checked=checked)};
window.startImportJobV19=async(all)=>{
  const job=state.activeImportJob;if(!job)return toast('没有可解析的导入任务');
  const selected=all?[]:$$('.impChk').filter(x=>x.checked).map(x=>x.value);
  if(!all&&!selected.length)return toast('请选择至少一张图片，或点击解析全部');
  const r=await safe(api(`/api/v19/projects/${pid()}/import/jobs/${job.id}/start`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selected_paths:selected})}));
  if(r){toast('已缩放到后台解析，右下角可查看进度');closeModal();await loadImportJobs();startImportPolling();}
};

// 页面启动后加载一次后台导入任务；有运行任务时继续轮询。
setTimeout(async()=>{ensureImportDock();await loadImportJobs();if((state.importJobs||[]).some(j=>j.status==='running'))startImportPolling();},600);

// -----------------------------
// v20：批量移动数据用途、飞桨环境检测、训练参数分层、版本报告跟随
// -----------------------------
state.selectedImages = new Set();
function helpIcon(key){return `<button type="button" class="help" onclick="helpParam('${key}')">?</button>`}
const HELP_TEXT={
  epochs:'训练轮次。轮次越多，训练时间越长；数据少时轮次过多也不一定有效。CPU 试跑建议 20-50。',
  imgsz:'训练输入图片尺寸。640 是常用值；CPU 慢时可降到 416。尺寸越大，小目标可能更好，但更慢。',
  batch:'每次训练送入的图片数量。CPU 建议 2-4；显存/内存不足时调小。Ultralytics 还支持 -1 自动估算批大小。',
  device:'训练设备。CPU 填 cpu；NVIDIA GPU 通常填 0。',
  patience:'早停轮数。连续这么多轮指标不提升就提前停止。数据少时可以适当小一点。',
  workers:'数据加载进程数。Windows/CPU 环境建议 0，避免多进程问题。',
  optimizer:'优化器。auto 由 Ultralytics 自动选择；也可选 SGD、Adam、AdamW、NAdam、RAdam、RMSProp。',
  lr0:'初始学习率。一般保持默认 0.01；小数据集不建议乱调。',
  lrf:'最终学习率比例。通常保持默认 0.01。',
  weight_decay:'权重衰减，用来抑制过拟合。默认 0.0005。',
  close_mosaic:'训练最后多少轮关闭 mosaic 增强。默认 10。',
  mosaic:'Mosaic 数据增强强度。数据少时有帮助，但场景很固定时可降低。',
  cache:'是否缓存图片。False 最稳；内存足够可设 ram；不建议一开始就开。',
  single_cls:'是否把所有标签当成一个类别训练。多类别检测不要开启。',
  pretrained:'加载当前选择的 .pt 权重继续训练。关闭后，官方YOLO模型会改成同架构随机初始化；自定义 best.pt 不允许假装从头训练。',
  rect:'矩形训练。速度可能更快，但普通检测先保持关闭。',
  amp:'自动混合精度。GPU训练通常建议开启；Ultralytics会自动检查兼容性。',
  cos_lr:'余弦学习率调度。一般保持关闭，需要更平滑的学习率衰减时再开启。',
  freeze:'冻结前N层。0表示不冻结；迁移学习、小数据集可适当冻结部分骨干层。'
};
window.helpParam=k=>modal('参数说明',`<div class="hint-card"><div class="item-title">${esc(k)}</div><div class="item-sub">${esc(HELP_TEXT[k]||'暂无说明')}</div></div>`);

function selectedCount(){return state.selectedImages?state.selectedImages.size:0}
window.toggleOneImage=(id,checked)=>{if(!state.selectedImages)state.selectedImages=new Set();checked?state.selectedImages.add(id):state.selectedImages.delete(id);const el=$('#selCount');if(el)el.textContent=selectedCount()};
window.toggleVisibleImages=(checked)=>{$$('.imgChk').forEach(c=>{c.checked=checked;toggleOneImage(c.value,checked)});render()};
window.clearSelectedImages=()=>{state.selectedImages=new Set();render()};
window.batchMoveImages=async(split,scope='selected')=>{
  const ids=[...(state.selectedImages||new Set())];
  if(scope==='selected'&&!ids.length)return toast('请先勾选素材');
  const body={image_ids:ids,split,dataset_id:state.datasetId,filter:state.imageFilter,scope};
  const r=await safe(api(`/api/v20/projects/${pid()}/images/batch_split`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));
  if(r){state.selectedImages=new Set();await loadRelated();render();toast(`已移动 ${r.changed} 个素材到${splitName(split)}`)}
};
window.bulkMoveMenu=()=>modal('批量移动素材',`<div class="form"><div class="hint-card">当前已选 ${selectedCount()} 个素材。也可以按当前筛选条件批量移动，例如把“未标注”或“训练集”当前筛选结果移动到其他用途。</div><div class="field"><label>移动已选素材到</label><div class="row"><button class="btn primary" onclick="batchMoveImages('train','selected')">训练集</button><button class="btn" onclick="batchMoveImages('val','selected')">评测集</button><button class="btn" onclick="batchMoveImages('test','selected')">试验集</button></div></div><div class="field"><label>移动当前筛选结果到</label><div class="row"><button class="btn soft" onclick="batchMoveImages('train','filtered')">训练集</button><button class="btn soft" onclick="batchMoveImages('val','filtered')">评测集</button><button class="btn soft" onclick="batchMoveImages('test','filtered')">试验集</button></div></div></div>`);

function renderResources(){
  const resourceCards = state.targets.map(t=>`<div class="res-card ${t.status==='ready'?'ready':'warn'}"><div class="res-main"><div class="res-icon">${t.framework==='paddle'?'桨':t.type==='server'?'服':'U'}</div><div><div class="item-title">${esc(t.name)}</div><div class="item-sub">${t.framework==='paddle'?'飞桨':t.framework==='ultralytics'?'Ultralytics':'未知'} · ${t.type==='server'?'训练服务器':'本机环境'} ${t.version?'· '+esc(t.version):''}</div></div></div><div class="res-meta"><span class="pill ${t.status==='ready'?'ok':'warn'}">${t.status==='ready'?'可用':'待配置'}</span><span class="pill blue">${(t.algorithms||[]).length} 个算法</span><span class="pill">${(t.base_models||[]).length} 个权重</span></div></div>`).join('');
  $('#view').innerHTML=`<div class="resource-layout"><section class="panel"><div class="panel-head"><div class="panel-title">接入训练资源</div><button class="btn small" onclick="loadAll().then(render)">刷新</button></div><div class="panel-body"><div class="resource-actions"><div class="quick-card"><div class="quick-title">本机 Ultralytics</div><div class="field"><label>安装目录</label><input id="uroot" class="input"></div><div class="row"><button class="btn primary small" onclick="detectUltra()">检测并启用</button><button class="btn soft small" onclick="quickUltraDetect()">一键检测</button></div></div><div class="quick-card"><div class="quick-title">本机飞桨</div><div class="field"><label>Python路径</label><input id="ppy" class="input"></div><div class="field"><label>PaddleDetection目录</label><input id="pdet" class="input"></div><div class="field"><label>PaddleX目录</label><input id="pxdir" class="input"></div><div class="row"><button class="btn primary small" onclick="detectPaddle()">检测并启用</button><button class="btn soft small" onclick="quickPaddleDetect()">一键检测</button><button class="btn small" onclick="testPaddle()">只检测</button></div><div id="paddleTestResult" class="item-sub"></div></div><div class="quick-card"><div class="quick-title">本机模型目录</div><div class="field"><label>模型目录</label><input id="scanRoot" class="input"></div><button class="btn small" onclick="scanModels()">扫描模型</button></div><div class="quick-card"><div class="quick-title">训练服务器</div><div class="field"><label>服务地址</label><input id="quickServerUrl" class="input" placeholder="http://192.168.1.10:8020"></div><button class="btn soft small" onclick="quickAddServer()">接入服务器</button></div></div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">已接入资源</div></div><div class="panel-body"><div class="resource-grid">${resourceCards||'<div class="empty">暂无资源。先检测本机 Ultralytics 或飞桨。</div>'}</div></div></section></div>`;
}
window.testPaddle=async()=>{const body={name:'本机飞桨',python_path:$('#ppy').value,paddledet_dir:$('#pdet').value,paddlex_dir:$('#pxdir').value};const r=await safe(api('/api/paddle_env/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));if(r){$('#paddleTestResult').textContent=`paddle=${r.modules?.paddle||'-'}，paddlex=${r.modules?.paddlex||'-'}，PaddleDetection=${r.paddledet_exists?'存在':'未找到'}`;toast('飞桨检测完成')}};
window.detectPaddle=async()=>{const body={name:'本机飞桨',python_path:$('#ppy').value,paddledet_dir:$('#pdet').value,paddlex_dir:$('#pxdir').value};await safe(api('/api/paddle_env/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));await testPaddle();await loadAll();render();toast('已保存飞桨环境')};
window.quickPaddleDetect=async()=>{const r=await safe(api('/api/paddle_env/detect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}));const env=(r?.candidates||[])[0];if(!env)return toast('未检测到飞桨环境，请手动填写 Python 路径');await safe(api('/api/paddle_env/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(env)}));await loadAll();render();toast('已启用飞桨环境')};

function renderTraining(){
  const rec=state.rec?.recommendation||{};
  $('#view').innerHTML=`<div class="grid2"><section class="panel"><div class="panel-head"><div class="panel-title">创建训练任务</div><span class="pill ok">推荐 ${esc(rec.model||'yolo11n.pt')} / ${esc(rec.device||'cpu')}</span></div><div class="panel-body"><div class="train-tabs"><button class="on">基础配置</button><button onclick="document.getElementById('advCfg').classList.toggle('hidden')">展开/收起进阶配置</button></div><div class="form two"><div class="field"><label>训练数据集</label><select class="select" id="trainDataset">${state.datasets.map(d=>`<option value="${d.id}" ${d.id===state.datasetId?'selected':''}>${esc(d.name)}（${d.images}图）</option>`).join('')}</select></div><div class="field"><label>训练资源</label><select class="select" id="target" onchange="fillTrain()">${state.targets.map(t=>`<option value="${t.id}">${esc(t.name)} / ${t.type==='server'?'服务器':'本机'}</option>`).join('')}</select></div><div class="field"><label>训练算法</label><select class="select" id="alg" onchange="applyAlg()"></select></div><div class="field"><label>基础模型权重</label><select class="select" id="model"></select></div><div class="field"><label>训练轮次 ${helpIcon('epochs')}</label><input class="input" id="epochs" value="${rec.epochs||20}"></div><div class="field"><label>图片尺寸 ${helpIcon('imgsz')}</label><input class="input" id="imgsz" value="${rec.imgsz||640}"></div><div class="field"><label>批大小 ${helpIcon('batch')}</label><input class="input" id="batch" value="${rec.batch||4}"></div><div class="field"><label>训练设备 ${helpIcon('device')}</label><input class="input" id="device" value="${rec.device||'cpu'}"></div></div><div id="advCfg" class="form two adv hidden"><div class="field"><label>早停轮数 ${helpIcon('patience')}</label><input class="input" id="patience" value="100"></div><div class="field"><label>数据加载进程 ${helpIcon('workers')}</label><input class="input" id="workers" value="0"></div><div class="field"><label>优化器 ${helpIcon('optimizer')}</label><select class="select" id="optimizer"><option value="auto">auto</option><option value="SGD">SGD</option><option value="Adam">Adam</option><option value="AdamW">AdamW</option><option value="NAdam">NAdam</option><option value="RAdam">RAdam</option><option value="RMSProp">RMSProp</option></select></div><div class="field"><label>初始学习率 ${helpIcon('lr0')}</label><input class="input" id="lr0" value="0.01"></div><div class="field"><label>最终学习率比例 ${helpIcon('lrf')}</label><input class="input" id="lrf" value="0.01"></div><div class="field"><label>权重衰减 ${helpIcon('weight_decay')}</label><input class="input" id="weight_decay" value="0.0005"></div><div class="field"><label>关闭Mosaic轮数 ${helpIcon('close_mosaic')}</label><input class="input" id="close_mosaic" value="10"></div><div class="field"><label>Mosaic强度 ${helpIcon('mosaic')}</label><input class="input" id="mosaic" value="1.0"></div><div class="field"><label>缓存 ${helpIcon('cache')}</label><select class="select" id="cache"><option value="False">关闭</option><option value="ram">内存缓存</option><option value="disk">磁盘缓存</option></select></div><div class="field check"><label><input type="checkbox" id="single_cls"> 单类别训练 ${helpIcon('single_cls')}</label></div><div class="field check"><label><input type="checkbox" id="pretrained" checked> 加载所选权重（推荐） ${helpIcon('pretrained')}</label></div><div class="field check"><label><input type="checkbox" id="rect"> 矩形训练 ${helpIcon('rect')}</label></div><div class="field check"><label><input type="checkbox" id="amp" checked> AMP混合精度 ${helpIcon('amp')}</label></div><div class="field check"><label><input type="checkbox" id="cos_lr"> 余弦学习率 ${helpIcon('cos_lr')}</label></div><div class="field"><label>冻结前N层 ${helpIcon('freeze')}</label><input class="input" id="freeze" value="0"></div></div><div class="divider"></div><button class="btn primary" onclick="startTrain()">开始训练</button></div></section><section class="panel"><div class="panel-head"><div class="panel-title">任务列表</div><button class="btn small" onclick="loadAll().then(render)">刷新</button></div><div class="panel-body"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>数据集</th><th>操作</th></tr></thead><tbody>${state.jobs.map(j=>`<tr><td>${esc(j.algorithm_name||j.id)}</td><td><span class="pill ${j.status==='done'||j.status==='finished'?'ok':j.status==='failed'?'err':'warn'}">${statusName(j.status)}</span></td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td><div class="row"><button class="btn small" onclick="showLog('${j.id}')">日志</button><button class="btn small danger" onclick="stopJob('${j.id}')">停止</button><button class="btn small danger" onclick="deleteJob('${j.id}')">删除</button></div></td></tr>`).join('')||'<tr><td colspan="4">暂无训练任务</td></tr>'}</tbody></table></div></section></div><section class="panel"><div class="panel-head"><div class="panel-title">训练日志</div></div><div class="panel-body"><pre id="log" class="log">选择任务查看日志</pre></div></section>`;
  fillTrain();
}

window.assignVersion=name=>{if(!state.algorithms.length)return toast('请先在算法列表创建算法');const m=(state.pending||[]).find(x=>x.name===name)||{};state.assigningModel=m;modal('发布为算法版本',`<div class="form"><div class="field"><label>模型</label><input class="input" value="${esc(name)}" disabled></div><div class="field"><label>来源训练任务</label><input class="input" value="${esc(m.job_name||m.job_id||'未绑定训练任务，报告会按模型文件生成') }" disabled></div><div class="field"><label>算法</label><select id="algoSel" class="select">${state.algorithms.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></div><div class="field"><label>版本名称</label><input id="verName" class="input" placeholder="例如：V1.0"></div><div class="field"><label>备注</label><textarea id="verRemark"></textarea></div><button class="btn primary" onclick="saveAssign('${esc(name)}')">发布为算法版本</button></div>`)};
window.saveAssign=async name=>{const m=state.assigningModel||{},aid=$('#algoSel').value;const r=await safe(api(`/api/v12/projects/${pid()}/algorithms/${aid}/versions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_name:name,model_source:'project',version_name:$('#verName').value,remark:$('#verRemark').value,job_id:m.job_id||''})}));if(!r?.version)return;const a=(state.algorithms||[]).find(x=>x.id===aid);if(a)a.versions=[r.version,...(a.versions||[]).filter(v=>v.id!==r.version.id)];state.pending=(state.pending||[]).filter(x=>x.name!==name&&(!r.version.model_key||x.model_key!==r.version.model_key));state.assigningModel=null;closeModal();render();toast('已发布为算法版本')};
window.showReport=(aid,vid)=>{const a=state.algorithms.find(x=>x.id===aid);const v=a.versions.find(x=>x.id===vid);const rep=v.report||{};modal('算法版本训练报告',`<div class="hint-card"><div class="item-title">${esc(a.name)} / ${esc(v.version_name||'版本')}</div><div class="item-sub">报告跟随该算法版本保存，后续打开版本仍可查看训练来源、参数、指标和模型文件信息。</div></div><div class="report">${Object.entries(rep).map(([k,val])=>`<div><b>${esc(k)}</b><span>${esc(val)}</span></div>`).join('')||'<div>暂无报告</div>'}</div>`,true)};

// -----------------------------
// v21 飞桨识别增强：扫描 PaddleDetection/configs 真实可训练算法，不再写死 PP-YOLOE
// -----------------------------
function familySummary(t){
  const fam=t?.scan?.families||t?.algorithm_scan?.families||{};
  const arr=Object.entries(fam).slice(0,6).map(([k,v])=>`${k} ${v}`);
  return arr.length?arr.join(' · '):'';
}
function algoBadge(a){
  const bits=[]; if(a.family)bits.push(a.family); if(a.size)bits.push(a.size); if(a.default_imgsz)bits.push(String(a.default_imgsz)); if(a.backbone)bits.push(a.backbone);
  return bits.join(' / ');
}
function groupAlgos(list){
  const m={};(list||[]).forEach(a=>{const k=a.family||a.engine||'其他';(m[k]=m[k]||[]).push(a)});return m;
}
function renderAlgoListForModal(algos){
  const groups=groupAlgos(algos||[]);
  return Object.entries(groups).map(([fam,items])=>`<div class="algo-group"><div class="algo-group-title">${esc(fam)} <span>${items.length} 个</span></div>${items.map(a=>`<div class="item compact"><div><div class="item-title">${esc(a.name)}</div><div class="item-sub">${esc(a.config_relpath||a.base_model||'')} ${a.recommended?' · 推荐先试':''}</div></div><span class="pill blue">${esc(algoBadge(a)||'目标检测')}</span></div>`).join('')}</div>`).join('')||'<div class="empty">没有识别到 PaddleDetection 可训练配置。</div>';
}
window.viewResourceAlgorithms=(targetId)=>{
  const t=(state.targets||[]).find(x=>x.id===targetId); if(!t)return;
  modal(`${t.name} · 可训练算法`, `<div class="hint-card"><div class="item-title">识别结果：${(t.algorithms||[]).length} 个算法配置</div><div class="item-sub">${esc(familySummary(t)||'系统会扫描 PaddleDetection/configs 目录下的 .yml/.yaml 配置，并自动生成训练命令模板。')}</div></div>${renderAlgoListForModal(t.algorithms||[])}`, true);
};
function renderResources(){
  const resourceCards = (state.targets||[]).map(t=>`<div class="res-card ${t.status==='ready'?'ready':'warn'}">
    <div class="res-main"><div class="res-icon">${t.framework==='paddle'?'桨':t.type==='server'?'服':'U'}</div><div><div class="item-title">${esc(t.name)}</div><div class="item-sub">${t.framework==='paddle'?'飞桨 PaddleDetection':t.framework==='ultralytics'?'Ultralytics':'未知'} · ${t.type==='server'?'训练服务器':'本机环境'} ${t.version?'· '+esc(t.version):''}</div>${t.framework==='paddle'?`<div class="item-sub">${esc(familySummary(t)||t.scan?.error||'未扫描到 configs，请确认 PaddleDetection 目录')}</div>`:''}</div></div>
    <div class="res-meta"><span class="pill ${t.status==='ready'?'ok':'warn'}">${t.status==='ready'?'可用':t.status==='offline'?'不可用':'待确认'}</span><span class="pill blue">${(t.algorithms||[]).length} 个算法</span><span class="pill">${(t.base_models||[]).length} 个权重</span>${t.framework==='paddle'?`<button class="btn mini" onclick="viewResourceAlgorithms('${esc(t.id)}')">查看算法</button>`:''}</div>
  </div>`).join('');
  const paddle=(state.targets||[]).find(t=>t.id==='local_paddle')||{};
  $('#view').innerHTML=`<div class="resource-layout"><section class="panel"><div class="panel-head"><div class="panel-title">接入训练资源</div><button class="btn small" onclick="loadAll().then(render)">刷新</button></div><div class="panel-body"><div class="resource-actions"><div class="quick-card"><div class="quick-title">本机 Ultralytics</div><div class="field"><label>安装目录</label><input id="uroot" class="input"></div><div class="row"><button class="btn primary small" onclick="detectUltra()">检测并启用</button><button class="btn soft small" onclick="quickUltraDetect()">一键检测</button></div></div><div class="quick-card"><div class="quick-title">本机飞桨</div><div class="field"><label>Python路径</label><input id="ppy" class="input" value="${esc(paddle.python_path||'')}"></div><div class="field"><label>PaddleDetection目录</label><input id="pdet" class="input" value="${esc(paddle.paddledet_dir||'')}"></div><div class="field"><label>PaddleX目录</label><input id="pxdir" class="input" value="${esc(paddle.paddlex_dir||'')}"></div><div class="row"><button class="btn primary small" onclick="detectPaddle()">检测并启用</button><button class="btn soft small" onclick="quickPaddleDetect()">一键检测</button><button class="btn small" onclick="testPaddle()">只检测</button></div><div id="paddleTestResult" class="item-sub"></div></div><div class="quick-card"><div class="quick-title">本机模型目录</div><div class="field"><label>模型目录</label><input id="scanRoot" class="input"></div><button class="btn small" onclick="scanModels()">扫描模型</button></div><div class="quick-card"><div class="quick-title">训练服务器</div><div class="field"><label>服务地址</label><input id="quickServerUrl" class="input" placeholder="http://192.168.1.10:8020"></div><button class="btn soft small" onclick="quickAddServer()">接入服务器</button></div></div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">已接入资源</div></div><div class="panel-body"><div class="resource-grid">${resourceCards||'<div class="empty">暂无资源。先检测本机 Ultralytics 或飞桨。</div>'}</div></div></section></div>`;
}
window.testPaddle=async()=>{const body={name:'本机飞桨',python_path:$('#ppy').value,paddledet_dir:$('#pdet').value,paddlex_dir:$('#pxdir').value};const r=await safe(api('/api/paddle_env/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));if(r){const fam=Object.entries(r.algorithm_scan?.families||{}).map(([k,v])=>`${k}${v}`).join('、');$('#paddleTestResult').textContent=`paddle=${r.modules?.paddle||'-'}，ppdet=${r.modules?.ppdet||'-'}，paddlex=${r.modules?.paddlex||'-'}，算法配置=${r.algorithm_scan?.total||0} 个 ${fam?`（${fam}）`:''}`;toast('飞桨检测完成')}};
window.detectPaddle=async()=>{const body={name:'本机飞桨',python_path:$('#ppy').value,paddledet_dir:$('#pdet').value,paddlex_dir:$('#pxdir').value};await safe(api('/api/paddle_env/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));await testPaddle();await loadAll();render();toast('已保存飞桨环境，并扫描可训练算法')};
window.quickPaddleDetect=async()=>{const r=await safe(api('/api/paddle_env/detect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}));const env=(r?.candidates||[])[0];if(!env)return toast('未检测到飞桨环境，请手动填写 Python 路径');await safe(api('/api/paddle_env/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(env)}));await loadAll();render();toast(`已启用飞桨环境，识别到 ${env.algorithm_scan?.total||0} 个算法配置`)};

function renderTraining(){
  const rec=state.rec?.recommendation||{};
  $('#view').innerHTML=`<div class="grid2"><section class="panel"><div class="panel-head"><div><div class="panel-title">创建训练任务</div><div class="subline">训练算法从当前训练资源实时读取。飞桨会扫描 PaddleDetection/configs 下的真实 yml 配置。</div></div><span class="pill ok">推荐 ${esc(rec.model||'yolo11n.pt')} / ${esc(rec.device||'cpu')}</span></div><div class="panel-body"><div class="train-tabs"><button class="on">基础配置</button><button onclick="document.getElementById('advCfg').classList.toggle('hidden')">展开/收起进阶配置</button></div><div class="form two"><div class="field"><label>训练数据集</label><select class="select" id="trainDataset">${state.datasets.map(d=>`<option value="${d.id}" ${d.id===state.datasetId?'selected':''}>${esc(d.name)}（${d.images}图）</option>`).join('')}</select></div><div class="field"><label>训练资源</label><select class="select" id="target" onchange="fillTrain()">${state.targets.map(t=>`<option value="${t.id}">${esc(t.name)} / ${t.framework==='paddle'?'飞桨':t.type==='server'?'服务器':'Ultralytics'}</option>`).join('')}</select></div><div class="field"><label>训练算法</label><select class="select" id="alg" onchange="applyAlg()"></select><div id="algMeta" class="item-sub"></div></div><div class="field"><label>基础模型权重</label><select class="select" id="model"></select><div id="modelMeta" class="item-sub"></div></div><div class="field"><label>训练轮次 ${helpIcon('epochs')}</label><input class="input" id="epochs" value="${rec.epochs||20}"></div><div class="field"><label>图片尺寸 ${helpIcon('imgsz')}</label><input class="input" id="imgsz" value="${rec.imgsz||640}"></div><div class="field"><label>批大小 ${helpIcon('batch')}</label><input class="input" id="batch" value="${rec.batch||4}"></div><div class="field"><label>训练设备 ${helpIcon('device')}</label><input class="input" id="device" value="${rec.device||'cpu'}"></div></div><div id="advCfg" class="form two adv hidden"><div class="field"><label>早停轮数 ${helpIcon('patience')}</label><input class="input" id="patience" value="100"></div><div class="field"><label>数据加载进程 ${helpIcon('workers')}</label><input class="input" id="workers" value="0"></div><div class="field"><label>优化器 ${helpIcon('optimizer')}</label><select class="select" id="optimizer"><option value="auto">auto</option><option value="SGD">SGD</option><option value="Adam">Adam</option><option value="AdamW">AdamW</option><option value="NAdam">NAdam</option><option value="RAdam">RAdam</option><option value="RMSProp">RMSProp</option></select></div><div class="field"><label>初始学习率 ${helpIcon('lr0')}</label><input class="input" id="lr0" value="0.01"></div><div class="field"><label>最终学习率比例 ${helpIcon('lrf')}</label><input class="input" id="lrf" value="0.01"></div><div class="field"><label>权重衰减 ${helpIcon('weight_decay')}</label><input class="input" id="weight_decay" value="0.0005"></div><div class="field"><label>关闭Mosaic轮数 ${helpIcon('close_mosaic')}</label><input class="input" id="close_mosaic" value="10"></div><div class="field"><label>Mosaic强度 ${helpIcon('mosaic')}</label><input class="input" id="mosaic" value="1.0"></div><div class="field"><label>缓存 ${helpIcon('cache')}</label><select class="select" id="cache"><option value="False">关闭</option><option value="ram">内存缓存</option><option value="disk">磁盘缓存</option></select></div><div class="field check"><label><input type="checkbox" id="single_cls"> 单类别训练 ${helpIcon('single_cls')}</label></div><div class="field check"><label><input type="checkbox" id="pretrained" checked> 加载所选权重（推荐） ${helpIcon('pretrained')}</label></div><div class="field check"><label><input type="checkbox" id="rect"> 矩形训练 ${helpIcon('rect')}</label></div><div class="field check"><label><input type="checkbox" id="amp" checked> AMP混合精度 ${helpIcon('amp')}</label></div><div class="field check"><label><input type="checkbox" id="cos_lr"> 余弦学习率 ${helpIcon('cos_lr')}</label></div><div class="field"><label>冻结前N层 ${helpIcon('freeze')}</label><input class="input" id="freeze" value="0"></div></div><div class="divider"></div><button class="btn primary" onclick="startTrain()">开始训练</button></div></section><section class="panel"><div class="panel-head"><div class="panel-title">任务列表</div><button class="btn small" onclick="loadAll().then(render)">刷新</button></div><div class="panel-body"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>数据集</th><th>操作</th></tr></thead><tbody>${state.jobs.map(j=>`<tr><td>${esc(j.algorithm_name||j.id)}</td><td><span class="pill ${j.status==='done'||j.status==='finished'?'ok':j.status==='failed'?'err':'warn'}">${statusName(j.status)}</span></td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td><div class="row"><button class="btn small" onclick="showLog('${j.id}')">日志</button><button class="btn small danger" onclick="stopJob('${j.id}')">停止</button><button class="btn small danger" onclick="deleteJob('${j.id}')">删除</button></div></td></tr>`).join('')||'<tr><td colspan="4">暂无训练任务</td></tr>'}</tbody></table></div></section></div><section class="panel"><div class="panel-head"><div class="panel-title">训练日志</div></div><div class="panel-body"><pre id="log" class="log">选择任务查看日志</pre></div></section>`;
  fillTrain();
}
window.fillTrain=()=>{const t=curTarget(),a=$('#alg'),m=$('#model');if(!t||!a||!m)return;const algs=t.algorithms||[];const groups=groupAlgos(algs);a.innerHTML=Object.entries(groups).map(([fam,items])=>`<optgroup label="${esc(fam)}">${items.map(x=>`<option value="${esc(x.key)}">${esc(x.name)}${x.recommended?'（推荐）':''}</option>`).join('')}</optgroup>`).join('')||'<option value="">无可用算法</option>';m.innerHTML=(t.base_models||[]).map(x=>`<option value="${esc(x.value||'')}" data-note="${esc(x.source||'')}">${esc(x.label||x.value||'默认权重')}</option>`).join('')||'<option value="">默认权重</option>';applyAlg()};
window.applyAlg=()=>{const t=curTarget();const alg=(t?.algorithms||[]).find(x=>x.key===$('#alg')?.value);if(!alg)return;$('#epochs').value=alg.default_epochs||$('#epochs').value;$('#imgsz').value=alg.default_imgsz||$('#imgsz').value;$('#batch').value=alg.default_batch||$('#batch').value;const meta=$('#algMeta');if(meta)meta.textContent=alg.config_relpath?`配置：${alg.config_relpath}；${algoBadge(alg)}`:(alg.description||'');const mm=$('#modelMeta');if(mm)mm.textContent=(t.framework==='paddle')?'留空表示使用配置默认预训练权重/自动下载；选择 .pdparams 可作为 pretrain_weights。':'请选择 .pt 训练权重。';const m=$('#model');const hit=[...m.options].find(o=>(o.value||o.textContent).toLowerCase().includes(String(alg.base_model||'').toLowerCase()));if(hit)m.value=hit.value};


// -----------------------------
// v23 训练状态实时刷新 + 独立检测台
// -----------------------------
if (!navs.includes('检测台')) navs.push('检测台');
state.activeLogJob = state.activeLogJob || null;

function statusPillClass(s){return ['done','finished'].includes(s)?'ok':s==='failed'?'err':s==='stopped'?'blue':s==='running'?'warn':'warn'}
function jobEtaText(j){if(['done','finished'].includes(j.status))return '已完成'; if(j.status==='failed')return '失败'; if(j.status==='stopped')return '已停止'; return j.eta_text||'估算中'}
function renderJobProgress(j){
  const pct=Math.max(0,Math.min(100,Number(j.progress_percent||0)));
  const cur=Number(j.current_epoch||0), total=Number(j.total_epochs||j.epochs||0);
  const ep=total?`${cur||0}/${total}轮`:'-';
  return `<div class="job-progress"><div class="job-progress-top"><span>${ep}</span><span>${pct}%</span></div><div class="bar"><i style="width:${pct}%"></i></div><div class="item-sub">已用 ${esc(j.elapsed_text||'-')} · 剩余 ${esc(jobEtaText(j))}</div></div>`;
}
function hasLiveJob(){return (state.jobs||[]).some(j=>['queued','running','waiting','pending'].includes(j.status));}
async function pollActiveLog(){if(!state.activeLogJob)return;const el=$('#log');if(!el)return;const txt=await safe(api(`/api/projects/${pid()}/jobs/${state.activeLogJob}/log`));if(txt!=null)el.textContent=txt||'暂无日志';el.scrollTop=el.scrollHeight;}
render=function(){renderNav();renderTop();renderSummary();({算法列表:renderAlgorithms,训练资源:renderResources,数据集:renderDatasets,训练任务:renderTraining,测试发布:renderTest,检测台:renderDetectBench}[state.page]||renderAlgorithms)();window.PollRegistryRuntime?.replaceTrainingJobTimer?.();}

function renderTraining(){
  const rec=state.rec?.recommendation||{};
  const rows=(state.jobs||[]).map(j=>`<tr><td><div class="item-title">${esc(j.algorithm_name||j.id)}</div><div class="item-sub">${esc(j.framework||'')} · ${esc(j.run_name||'')}</div></td><td><span class="pill ${statusPillClass(j.status)}">${esc(j.status_text||statusName(j.status))}</span><div class="item-sub">${esc(j.message||'')}</div></td><td>${renderJobProgress(j)}</td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td><div class="row"><button class="btn small" onclick="showLog('${j.id}')">日志</button><button class="btn small danger" onclick="stopJob('${j.id}')">停止</button><button class="btn small danger" onclick="deleteJob('${j.id}')">删除</button></div></td></tr>`).join('')||'<tr><td colspan="5">暂无训练任务</td></tr>';
  $('#view').innerHTML=`<div class="grid2"><section class="panel"><div class="panel-head"><div><div class="panel-title">创建训练任务</div><div class="subline">训练算法从当前训练资源实时读取。任务启动后状态、轮次进度和预计剩余时间会自动刷新。</div></div><span class="pill ok">推荐 ${esc(rec.model||'yolo11n.pt')} / ${esc(rec.device||'cpu')}</span></div><div class="panel-body"><div class="train-tabs"><button class="on">基础配置</button><button onclick="document.getElementById('advCfg').classList.toggle('hidden')">展开/收起进阶配置</button></div><div class="form two"><div class="field"><label>训练数据集</label><select class="select" id="trainDataset">${state.datasets.map(d=>`<option value="${d.id}" ${d.id===state.datasetId?'selected':''}>${esc(d.name)}（${d.images}图）</option>`).join('')}</select></div><div class="field"><label>训练资源</label><select class="select" id="target" onchange="fillTrain()">${state.targets.map(t=>`<option value="${t.id}">${esc(t.name)} / ${t.framework==='paddle'?'飞桨':t.type==='server'?'服务器':'Ultralytics'}</option>`).join('')}</select></div><div class="field"><label>训练算法</label><select class="select" id="alg" onchange="applyAlg()"></select><div id="algMeta" class="item-sub"></div></div><div class="field"><label>基础模型权重</label><select class="select" id="model"></select><div id="modelMeta" class="item-sub"></div></div><div class="field"><label>训练轮次 ${helpIcon('epochs')}</label><input class="input" id="epochs" value="${rec.epochs||20}"></div><div class="field"><label>图片尺寸 ${helpIcon('imgsz')}</label><input class="input" id="imgsz" value="${rec.imgsz||640}"></div><div class="field"><label>批大小 ${helpIcon('batch')}</label><input class="input" id="batch" value="${rec.batch||4}"></div><div class="field"><label>训练设备 ${helpIcon('device')}</label><input class="input" id="device" value="${rec.device||'cpu'}"></div></div><div id="advCfg" class="form two adv hidden"><div class="field"><label>早停轮数 ${helpIcon('patience')}</label><input class="input" id="patience" value="100"></div><div class="field"><label>数据加载进程 ${helpIcon('workers')}</label><input class="input" id="workers" value="0"></div><div class="field"><label>优化器 ${helpIcon('optimizer')}</label><select class="select" id="optimizer"><option value="auto">auto</option><option value="SGD">SGD</option><option value="Adam">Adam</option><option value="AdamW">AdamW</option><option value="NAdam">NAdam</option><option value="RAdam">RAdam</option><option value="RMSProp">RMSProp</option></select></div><div class="field"><label>初始学习率 ${helpIcon('lr0')}</label><input class="input" id="lr0" value="0.01"></div><div class="field"><label>最终学习率比例 ${helpIcon('lrf')}</label><input class="input" id="lrf" value="0.01"></div><div class="field"><label>权重衰减 ${helpIcon('weight_decay')}</label><input class="input" id="weight_decay" value="0.0005"></div><div class="field"><label>关闭Mosaic轮数 ${helpIcon('close_mosaic')}</label><input class="input" id="close_mosaic" value="10"></div><div class="field"><label>Mosaic强度 ${helpIcon('mosaic')}</label><input class="input" id="mosaic" value="1.0"></div><div class="field"><label>缓存 ${helpIcon('cache')}</label><select class="select" id="cache"><option value="False">关闭</option><option value="ram">内存缓存</option><option value="disk">磁盘缓存</option></select></div><div class="field check"><label><input type="checkbox" id="single_cls"> 单类别训练 ${helpIcon('single_cls')}</label></div><div class="field check"><label><input type="checkbox" id="pretrained" checked> 加载所选权重（推荐） ${helpIcon('pretrained')}</label></div><div class="field check"><label><input type="checkbox" id="rect"> 矩形训练 ${helpIcon('rect')}</label></div><div class="field check"><label><input type="checkbox" id="amp" checked> AMP混合精度 ${helpIcon('amp')}</label></div><div class="field check"><label><input type="checkbox" id="cos_lr"> 余弦学习率 ${helpIcon('cos_lr')}</label></div><div class="field"><label>冻结前N层 ${helpIcon('freeze')}</label><input class="input" id="freeze" value="0"></div></div><div class="divider"></div><button class="btn primary" onclick="startTrain()">开始训练</button></div></section><section class="panel"><div class="panel-head"><div class="panel-title">任务列表</div><button class="btn small" onclick="loadAll().then(render)">刷新</button></div><div class="panel-body"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>进度 / 倒计时</th><th>数据集</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div></section></div><section class="panel"><div class="panel-head"><div class="panel-title">训练日志</div><div class="row"><span class="item-sub">${state.activeLogJob?'自动刷新中':'选择任务查看日志'}</span></div></div><div class="panel-body"><pre id="log" class="log">选择任务查看日志</pre></div></section>`;
  fillTrain();
  if(state.activeLogJob) pollActiveLog();
}
window.showLog=async(id,silent=false)=>{state.activeLogJob=id;const el=$('#log');if(el){el.textContent=await safe(api(`/api/projects/${pid()}/jobs/${id}/log`))||'暂无日志';el.scrollTop=el.scrollHeight;}if(!silent)toast('已打开日志，后续自动刷新')};

function modelOptionsHtml(selectedIndex=0){return (state.testModels||[]).map((m,i)=>`<option value="${i}" data-fw="${esc(m.framework||'ultralytics')}">${esc(m.label)}</option>`).join('')||'<option value="">暂无可测试模型</option>'}
function pickEnvForFramework(fw){return (state.inferenceEnvs||[]).find(e=>e.framework===fw&&e.status==='ready') || (state.inferenceEnvs||[]).find(e=>e.status==='ready') || {};}
function renderDetectionResult(r,title){return `<div class="compare-card"><div class="compare-head"><b>${esc(title)}</b><span>${esc(r.engine||'')} · ${esc(r.elapsed_ms||0)}ms · ${esc((r.detections||[]).length)}个结果</span></div>${r.image_url?`<img class="result-img" src="${r.image_url}">`:''}<table class="table mini-table"><thead><tr><th>标签</th><th>置信度</th><th>坐标</th></tr></thead><tbody>${(r.detections||[]).map(d=>`<tr><td>${esc(d.label)}</td><td>${esc(d.confidence)}</td><td>${esc(d.x1)},${esc(d.y1)},${esc(d.x2)},${esc(d.y2)}</td></tr>`).join('')||'<tr><td colspan="3">无结果</td></tr>'}</tbody></table></div>`}
async function benchPredictOne(selectId,file,conf){const m=state.testModels[+$(selectId).value];if(!m)throw new Error('请选择模型');const fw=m.framework||($(selectId).selectedOptions[0]?.dataset.fw)||'ultralytics';const env=pickEnvForFramework(fw);const fd=new FormData();fd.append('file',file);fd.append('model_name',m.model_name||'');fd.append('model_source',m.model_source||'project');fd.append('local_path',m.path||'');fd.append('algorithm_id',m.algorithm_id||'');fd.append('version_id',m.version_id||'');fd.append('conf',conf);fd.append('inference_framework',fw);fd.append('inference_env_id',env.id||'');const r=await api(`/api/v12/projects/${pid()}/predict`,{method:'POST',body:fd});return {r,m,env};}
function renderDetectBench(){
  const live=(state.jobs||[]).filter(j=>['queued','running'].includes(j.status));
  $('#view').innerHTML=`<section class="panel"><div class="panel-head"><div><div class="panel-title">检测台</div><div class="subline">独立模型检测入口。可以用原始模型和训练后的新模型同图对比。</div></div><button class="btn small" onclick="loadAll().then(render)">刷新模型/环境</button></div><div class="panel-body"><div class="form two"><div class="field"><label>原始模型 / 对照模型</label><select class="select" id="benchModelA">${modelOptionsHtml(0)}</select></div><div class="field"><label>新模型 / 训练后模型</label><select class="select" id="benchModelB">${modelOptionsHtml(1)}</select></div><div class="field"><label>置信度</label><input class="input" id="benchConf" value="0.25"></div><div class="field"><label>测试图片</label><input id="benchFile" type="file" accept="image/*" class="file"></div></div><div class="row"><button class="btn primary" onclick="benchCompare()">同图对比检测</button><button class="btn soft" onclick="benchSingle('benchModelA')">只测左侧模型</button><button class="btn soft" onclick="benchSingle('benchModelB')">只测右侧模型</button></div><div id="benchResult" class="compare-grid"></div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">训练任务状态</div><span class="item-sub">检测时仍可观察后台训练</span></div><div class="panel-body"><div class="card-list">${live.map(j=>`<div class="item"><div><div class="item-title">${esc(j.algorithm_name||j.id)}</div>${renderJobProgress(j)}</div><span class="pill ${statusPillClass(j.status)}">${esc(j.status_text||statusName(j.status))}</span></div>`).join('')||'<div class="empty">当前没有运行中的训练任务</div>'}</div></div></section>`;
}
window.benchSingle=async(selectId)=>{const file=$('#benchFile')?.files?.[0];if(!file)return toast('请选择测试图片');const out=$('#benchResult');out.innerHTML='<div class="loading">检测中...</div>';try{const {r,m}=await benchPredictOne(selectId,file,$('#benchConf').value||0.25);out.innerHTML=renderDetectionResult(r,m.label||m.model_name||'模型检测')}catch(e){toast(e.message||e);out.innerHTML=''}};
window.benchCompare=async()=>{const file=$('#benchFile')?.files?.[0];if(!file)return toast('请选择测试图片');const out=$('#benchResult');out.innerHTML='<div class="loading">两个模型检测中...</div>';try{const a=await benchPredictOne('benchModelA',file,$('#benchConf').value||0.25);const b=await benchPredictOne('benchModelB',file,$('#benchConf').value||0.25);out.innerHTML=renderDetectionResult(a.r,a.m.label||'原始模型')+renderDetectionResult(b.r,b.m.label||'新模型')}catch(e){toast(e.message||e);out.innerHTML=''}};

// 初次加载后若脚本后续追加了检测台，再重绘一次导航。
setTimeout(()=>{try{renderNav()}catch(e){}},0);

// ===== v24 overrides: Paddle安全训练参数 + 更完整检测台 =====
(function(){
  const oldApplyAlg = window.applyAlg;
  window.applyAlg = function(){
    if (typeof oldApplyAlg === 'function') oldApplyAlg();
    const t = curTarget && curTarget();
    const alg = (t?.algorithms||[]).find(x=>x.key===$('#alg')?.value);
    if(!t || !alg) return;
    if(t.framework==='paddle'){
      if($('#device')) $('#device').value='cpu';
      if($('#lr0')) $('#lr0').value='0.001';
      if($('#workers')) $('#workers').value='0';
      if($('#optimizer')) $('#optimizer').value='auto';
      const m=$('#model');
      if(m) m.value=''; // 飞桨默认使用 yml 内置预训练权重自动下载，不能把 yml 当权重。
      const mm=$('#modelMeta');
      if(mm) mm.textContent='飞桨默认使用配置内置预训练权重并自动下载；只有本地 .pdparams 才需要手动选择。';
      const meta=$('#algMeta');
      if(meta) meta.textContent=(alg.config_relpath?`配置：${alg.config_relpath}；`: '') + '平台会自动覆盖类别数、数据集路径和安全学习率，避免 COCO 原配置导致 KeyError/NaN。';
    }
  };

  window.renderDetectionResult = function(r,title){
    const dets=r.detections||[];
    const rows=dets.map(d=>`<tr><td>${esc(d.label)}</td><td>${esc(d.confidence)}</td><td>${esc(d.x1)}, ${esc(d.y1)}, ${esc(d.x2)}, ${esc(d.y2)}</td></tr>`).join('') || '<tr><td colspan="3">无结构化明细；请看检测图。飞桨PaddleDetection模型目前优先展示绘制结果。</td></tr>';
    return `<div class="compare-card enhanced-result"><div class="compare-head"><div><b>${esc(title)}</b><div class="item-sub">${esc(r.model||'')} · ${esc(r.engine||'')} · ${esc(r.elapsed_ms||0)}ms</div></div><span class="pill ${dets.length?'ok':'warn'}">${dets.length} 个结果</span></div>${r.note?`<div class="alert warn mini-alert">${esc(r.note)}</div>`:''}${r.image_url?`<div class="result-img-wrap"><img class="result-img" src="${r.image_url}"></div>`:''}<table class="table mini-table"><thead><tr><th>标签</th><th>置信度</th><th>坐标</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  };

  window.renderDetectBench = function(){
    const live=(state.jobs||[]).filter(j=>['queued','running'].includes(j.status));
    const recent=(state.jobs||[]).slice(0,5);
    $('#view').innerHTML=`<section class="panel bench-panel"><div class="panel-head"><div><div class="panel-title">检测台</div><div class="subline">独立于发布流程。支持原始模型、新模型、飞桨模型、YOLO模型同图对比。</div></div><div class="row"><button class="btn small" onclick="loadAll().then(render)">刷新模型/环境</button><button class="btn soft small" onclick="resetBench()">清空</button></div></div><div class="panel-body"><div class="bench-layout"><div class="bench-config"><div class="form one"><div class="field"><label>原始模型 / 对照模型</label><select class="select" id="benchModelA">${modelOptionsHtml(0)}</select></div><div class="field"><label>新模型 / 训练后模型</label><select class="select" id="benchModelB">${modelOptionsHtml(1)}</select></div><div class="field"><label>置信度</label><div class="row"><input class="input" id="benchConf" value="0.25"><button class="btn mini" onclick="$('#benchConf').value='0.01'">0.01</button><button class="btn mini" onclick="$('#benchConf').value='0.25'">0.25</button><button class="btn mini" onclick="$('#benchConf').value='0.5'">0.5</button></div></div><div class="field"><label>测试图片</label><input id="benchFile" type="file" accept="image/*" class="file" onchange="previewBenchImage()"></div><div class="row wrap"><button class="btn primary" onclick="benchCompare()">同图对比检测</button><button class="btn soft" onclick="benchSingle('benchModelA')">只测左侧</button><button class="btn soft" onclick="benchSingle('benchModelB')">只测右侧</button></div></div></div><div class="bench-preview"><div class="item-title">原图预览</div><div id="benchPreview" class="preview-box">选择图片后显示原图</div><div class="item-sub">提示：新训练模型建议先用 0.01 低置信度看有没有学习到目标，再逐步提高到 0.25。</div></div></div><div id="benchResult" class="compare-grid"></div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">后台训练状态</div><span class="item-sub">检测时仍可观察训练倒计时</span></div><div class="panel-body"><div class="card-list">${live.map(j=>`<div class="item"><div><div class="item-title">${esc(j.algorithm_name||j.id)}</div>${renderJobProgress(j)}</div><span class="pill ${statusPillClass(j.status)}">${esc(j.status_text||statusName(j.status))}</span></div>`).join('')||'<div class="empty">当前没有运行中的训练任务</div>'}</div>${recent.length?`<div class="divider"></div><div class="item-sub">最近任务</div><table class="table mini-table"><tbody>${recent.map(j=>`<tr><td>${esc(j.algorithm_name||j.id)}</td><td>${esc(statusName(j.status))}</td><td>${renderJobProgress(j)}</td></tr>`).join('')}</tbody></table>`:''}</div></section>`;
  };

  window.previewBenchImage=function(){
    const f=$('#benchFile')?.files?.[0];
    const box=$('#benchPreview');
    if(!f||!box)return;
    const url=URL.createObjectURL(f);
    box.innerHTML=`<img class="preview-img" src="${url}">`;
  };
  window.resetBench=function(){
    const r=$('#benchResult'); if(r) r.innerHTML='';
    const p=$('#benchPreview'); if(p) p.textContent='选择图片后显示原图';
    const f=$('#benchFile'); if(f) f.value='';
  };

  window.benchCompare=async()=>{
    const file=$('#benchFile')?.files?.[0];if(!file)return toast('请选择测试图片');
    const out=$('#benchResult');out.innerHTML='<div class="loading">两个模型检测中，飞桨模型首次检测可能需要加载配置...</div>';
    try{
      const [a,b]=await Promise.all([benchPredictOne('benchModelA',file,$('#benchConf').value||0.25), benchPredictOne('benchModelB',file,$('#benchConf').value||0.25)]);
      out.innerHTML=renderDetectionResult(a.r,a.m.label||'原始模型')+renderDetectionResult(b.r,b.m.label||'新模型');
    }catch(e){toast(e.message||e);out.innerHTML=`<div class="alert err">${esc(e.message||e)}</div>`}
  };
})();

/* Dependencies shared with the final module runtime without exposing mutable app state. */
window.__resourceDiscoveryDependencies={
  request:(url,options)=>api(url,options),
  notify:message=>toast(message),
  modal:(title,body,wide)=>modal(title,body,wide),
  getPage:()=>state.page,
  refresh:async()=>{const page=state.page;await loadAll();state.page=page;render()}
};

/* v42.22 multi-source material storage UI. Physical storage never changes the image-id training contract. */
(()=>{
  const storageApi=()=>window.PlatformCore?.storage;
  state.storageSources61=state.storageSources61||[];
  state.materialSourceFilter61=state.materialSourceFilter61||'all';
  state.storageSourcesLoading61=false;

  async function loadStorageSources61(){
    if(state.storageSourcesLoading61)return state.storageSources61;
    state.storageSourcesLoading61=true;
    try{const response=await api('/api/v61/storage-sources');state.storageSources61=response.items||[];return state.storageSources61}
    finally{state.storageSourcesLoading61=false}
  }
  window.loadStorageSources61=loadStorageSources61;

  const previousNav61=renderNav;
  renderNav=function(){
    previousNav61();
    if(!state.v427Advanced)return;
    const groups=[...document.querySelectorAll('#nav .nav-group')],resource=groups.find(group=>group.querySelector('.nav-group-title')?.textContent.trim()==='资源配置');
    if(resource&&!resource.querySelector('[data-storage-nav="1"]'))resource.insertAdjacentHTML('beforeend',`<button data-storage-nav="1" class="nav-btn ${state.page==='素材存储配置'?'active':''}" onclick="setPage('素材存储配置')"><span class="nav-left"><i>▣</i><b>素材存储配置</b></span><span class="nav-arrow">›</span></button>`);
  };

  const typeName61=type=>({local:'本地存储',oss:'阿里云 OSS',s3:'S3 兼容',remote:'其他服务器'}[type]||type||'-');
  const health61=source=>source.health_status==='OK'||source.health_status==='AVAILABLE';
  function storageRows61(){
    const rows=state.storageSources61||[];
    return rows.map(source=>`<div class="storage61-row"><div><b>${esc(source.name)}</b><span>${esc(typeName61(source.type))}${source.is_default?' · 默认存储':''}</span></div><div><b>${esc(source.config?.endpoint||source.config?.base_url||source.config?.root||'-')}</b><span>${esc(source.config?.bucket||source.config?.namespace||source.config?.prefix||'')}</span></div><div><span class="pill ${health61(source)?'ok':source.health_status==='UNKNOWN'?'':'err'}">${esc(source.health_status==='UNKNOWN'?'未检测':source.health_status||'未检测')}</span><small>${esc(source.health_message||source.secret_masked||'')}</small></div><div><span class="pill ${source.enabled?'ok':''}">${source.enabled?'已启用':'已停用'}</span><small>${esc(source.last_checked_at?String(source.last_checked_at).replace('T',' ').slice(0,19):'')}</small></div><div class="row"><button class="btn mini" onclick="testStorageSource61('${source.id}')">测试连接</button><button class="btn mini" onclick="openStorageSource61('${source.id}')">编辑</button>${!source.is_default&&source.enabled?`<button class="btn mini" onclick="defaultStorageSource61('${source.id}')">设为默认</button>`:''}${source.id!=='default_local'?`<button class="btn mini" onclick="toggleStorageSource61('${source.id}',${source.enabled?'false':'true'})">${source.enabled?'停用':'启用'}</button><button class="btn mini danger" onclick="deleteStorageSource61('${source.id}')">删除</button>`:''}</div></div>`).join('')||'<div class="empty">暂无素材存储源</div>';
  }
  window.renderStorageSources61=async function(){
    const view=document.getElementById('view');if(!view)return;
    view.innerHTML=`<section class="storage61-shell"><div class="label414-head"><div><h2>素材存储配置</h2><p>所有位置共同组成统一素材池；训练仍只按图片 ID 精确选择。</p></div><div class="row"><button class="btn" onclick="openStorageImport61()">从存储导入素材</button><button class="btn primary" onclick="openStorageSource61()">＋ 新增存储源</button></div></div><section class="panel"><div class="storage61-table"><div class="storage61-row head"><span>名称 / 类型</span><span>地址 / Bucket</span><span>连接状态</span><span>启用状态</span><span>操作</span></div><div id="storage61Rows"><div class="empty">正在读取存储配置…</div></div></div></section><div class="storage61-note"><b>安全与兼容</b><span>密钥只保存到系统安全凭据库，浏览器不会读取真实密钥。历史 project/uploads 素材继续由“平台本地存储”管理，不移动原文件。</span></div></section>`;
    try{await loadStorageSources61();const rows=document.getElementById('storage61Rows');if(rows){rows.innerHTML=storageRows61();[...rows.children].forEach((row,index)=>{const source=state.storageSources61[index];if(!source?.enabled)return;const button=document.createElement('button');button.className='btn mini';button.textContent='重新扫描 / 恢复';button.onclick=()=>openStorageRescan61(source.id);row.querySelector('.row')?.appendChild(button)})}}
    catch(error){const rows=document.getElementById('storage61Rows');if(rows)rows.innerHTML=`<div class="alert err">${esc(error.message||error)}</div>`}
  };

  window.openStorageRescan61=async function(sourceId){
    const project=String(pid()||'');if(!project){toast('请先选择项目');return}
    const base=`/api/v61/projects/${encodeURIComponent(project)}`;
    const savedKey=`mc_storage_rescan_${project}_${sourceId}`;
    let taskId='',pollGeneration=0;
    try{taskId=localStorage.getItem(savedKey)||''}catch(_){}
    modal('存储源重新扫描 / 恢复',`<p>扫描当前项目引用的整个存储源，确认后同步新增、缺失和内容变化。</p><div id="sr61Status">正在读取任务…</div><div id="sr61Policy" hidden><label><input id="sr61New" type="checkbox" checked> 建立新增图片索引</label><br><label><input id="sr61Missing" type="checkbox" checked> 缺失文件标记不可用，保留索引</label><br><label><input id="sr61Changed" type="checkbox" checked> 更新变更内容，保留标注并标记需要复核</label><br><button id="sr61Confirm" class="btn primary">确认应用</button></div><div class="row"><button id="sr61Start" class="btn">开始新的扫描</button><button id="sr61Cancel" class="btn">取消任务</button><button class="btn" onclick="closeModal()">关闭</button></div>`,true);
    const target=document.getElementById('sr61Status'),selection=document.getElementById('sr61Policy');
    const endpoint=()=>`${base}/storage-rescans/${encodeURIComponent(taskId)}`;
    const active=()=>document.getElementById('sr61Status')===target;
    const terminal=status=>['SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE'].includes(status);
    async function poll(generation){
      try{
        const task=await api(endpoint());if(!active()||generation!==pollGeneration)return;
        const names={NEW:'新增',MISSING:'缺失',CHANGED:'内容变更',UNCHANGED:'未变',INVALID:'无法校验',SKIPPED:'跳过'};
        target.innerHTML=`<p>${esc(task.status)} · ${esc(task.current_item||task.stage||'')}</p><p>${Object.entries(names).map(([key,label])=>`${label} ${Number(task.counts?.[key]||0)}`).join(' · ')}</p>${Object.entries(task.examples||{}).filter(([,keys])=>keys.length).map(([key,keys])=>`<details><summary>${esc(names[key]||key)}示例</summary>${keys.map(value=>`<div>${esc(value)}</div>`).join('')}</details>`).join('')}${task.error?`<p class="alert err">${esc(task.error.message||'扫描失败')}</p>`:''}`;
        selection.hidden=task.status!=='AWAITING_CONFIRMATION';
        document.getElementById('sr61Start').disabled=!terminal(task.status);
        document.getElementById('sr61Cancel').disabled=terminal(task.status);
        if(!terminal(task.status)&&task.status!=='AWAITING_CONFIRMATION')setTimeout(()=>{if(active()&&generation===pollGeneration)poll(generation)},2000);
      }catch(error){if(active()){target.textContent=error.message||String(error);document.getElementById('sr61Start').disabled=false}}
    }
    document.getElementById('sr61Start').onclick=async()=>{
      const button=document.getElementById('sr61Start');button.disabled=true;
      try{const task=await api(`${base}/storage-sources/${encodeURIComponent(sourceId)}/rescans`,{method:'POST'});taskId=task.task_id;try{localStorage.setItem(savedKey,taskId)}catch(_){}poll(++pollGeneration)}catch(error){target.textContent=error.message||String(error);button.disabled=false}
    };
    document.getElementById('sr61Confirm').onclick=async()=>{
      const button=document.getElementById('sr61Confirm');button.disabled=true;
      try{await api(`${endpoint()}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({new:document.getElementById('sr61New').checked?'import':'ignore',missing:document.getElementById('sr61Missing').checked?'mark_unavailable':'ignore',changed:document.getElementById('sr61Changed').checked?'update':'ignore'})});selection.hidden=true;poll(++pollGeneration)}catch(error){target.textContent=error.message||String(error);button.disabled=false}
    };
    document.getElementById('sr61Cancel').onclick=async()=>{if(taskId){try{await api(`${endpoint()}/cancel`,{method:'POST'});poll(++pollGeneration)}catch(error){target.textContent=error.message||String(error)}}};
    if(taskId)poll(++pollGeneration);else{target.textContent='点击开始扫描。扫描进度按实际已核对对象计数。';document.getElementById('sr61Cancel').disabled=true}
  };

  function sourceFields61(type,source={}){
    const c=source.config||{},secret=source.secret_configured?'<small>密钥已配置；留空表示继续使用原密钥。</small>':'';
    if(type==='local')return `<div class="field full"><label>根目录</label><input id="ss61Root" class="input" value="${esc(c.root||'')}" placeholder="留空时由平台管理；也可填写跨平台配置路径"></div>`;
    if(type==='oss')return `<div class="field"><label>Endpoint *</label><input id="ss61Endpoint" class="input" value="${esc(c.endpoint||'')}"></div><div class="field"><label>Bucket *</label><input id="ss61Bucket" class="input" value="${esc(c.bucket||'')}"></div><div class="field"><label>Prefix</label><input id="ss61Prefix" class="input" value="${esc(c.prefix||'')}"></div><div class="field"><label>AccessKey ID</label><input id="ss61Access" class="input" autocomplete="off"></div><div class="field"><label>AccessKey Secret</label><input id="ss61Secret" type="password" class="input" autocomplete="new-password">${secret}</div>`;
    if(type==='s3')return `<div class="field"><label>Endpoint</label><input id="ss61Endpoint" class="input" value="${esc(c.endpoint||'')}" placeholder="AWS 可留空"></div><div class="field"><label>Region</label><input id="ss61Region" class="input" value="${esc(c.region||'')}"></div><div class="field"><label>Bucket *</label><input id="ss61Bucket" class="input" value="${esc(c.bucket||'')}"></div><div class="field"><label>Prefix</label><input id="ss61Prefix" class="input" value="${esc(c.prefix||'')}"></div><div class="field"><label>Access Key</label><input id="ss61Access" class="input" autocomplete="off"></div><div class="field"><label>Secret Key</label><input id="ss61Secret" type="password" class="input" autocomplete="new-password">${secret}</div><label class="field check"><input id="ss61Ssl" type="checkbox" ${c.use_ssl!==false?'checked':''}> 使用 SSL</label>`;
    return `<div class="field"><label>服务器地址 *</label><input id="ss61Base" class="input" value="${esc(c.base_url||'')}" placeholder="https://materials.example.com"></div><div class="field"><label>命名空间 *</label><input id="ss61Namespace" class="input" value="${esc(c.namespace||'')}"></div><div class="field"><label>根目录</label><input id="ss61Root" class="input" value="${esc(c.root||'')}"></div><div class="field"><label>API Token</label><input id="ss61Token" type="password" class="input" autocomplete="new-password">${secret}</div>`;
  }
  window.storageTypeChanged61=function(){const type=document.getElementById('ss61Type')?.value||'local',source=(state.storageSources61||[]).find(row=>row.id===state.storageEditing61)||{};const box=document.getElementById('ss61Fields');if(box)box.innerHTML=sourceFields61(type,source)};
  window.openStorageSource61=async function(id=''){
    await loadStorageSources61();const source=(state.storageSources61||[]).find(row=>row.id===id)||null;state.storageEditing61=id||'';const type=source?.type||'local';
    modal(source?'编辑素材存储源':'新增素材存储源',`<div class="storage61-form"><div class="form two"><div class="field"><label>名称 *</label><input id="ss61Name" class="input" value="${esc(source?.name||'')}"></div><div class="field"><label>类型 *</label><select id="ss61Type" class="select" onchange="storageTypeChanged61()" ${source?'disabled':''}>${Object.entries({local:'本地存储',oss:'阿里云 OSS',s3:'S3 兼容（AWS / MinIO）',remote:'其他服务器素材源'}).map(([value,label])=>`<option value="${value}" ${value===type?'selected':''}>${label}</option>`).join('')}</select></div></div><div id="ss61Fields" class="form two">${sourceFields61(type,source||{})}</div><label class="field check"><input id="ss61Enabled" type="checkbox" ${source?.enabled===false?'':'checked'}> 启用该存储源</label><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveStorageSource61()">保存</button></div></div>`,true);
  };
  function sourceValues61(){return {name:document.getElementById('ss61Name')?.value,type:document.getElementById('ss61Type')?.value,root:document.getElementById('ss61Root')?.value,endpoint:document.getElementById('ss61Endpoint')?.value,region:document.getElementById('ss61Region')?.value,bucket:document.getElementById('ss61Bucket')?.value,prefix:document.getElementById('ss61Prefix')?.value,access_key_id:document.getElementById('ss61Access')?.value,access_key_secret:document.getElementById('ss61Secret')?.value,secret_access_key:document.getElementById('ss61Secret')?.value,use_ssl:document.getElementById('ss61Ssl')?.checked,base_url:document.getElementById('ss61Base')?.value,namespace:document.getElementById('ss61Namespace')?.value,token:document.getElementById('ss61Token')?.value,enabled:document.getElementById('ss61Enabled')?.checked!==false}}
  window.saveStorageSource61=async function(){try{const payload=storageApi().buildStorageSourcePayload(sourceValues61()),id=state.storageEditing61;await api(id?`/api/v61/storage-sources/${id}`:'/api/v61/storage-sources',{method:id?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});closeModal();await loadStorageSources61();renderStorageSources61();toast('素材存储配置已保存')}catch(error){toast(error.message||error)}};
  window.testStorageSource61=async id=>{try{const response=await api(`/api/v61/storage-sources/${id}/test`,{method:'POST'});await loadStorageSources61();renderStorageSources61();toast(response.health?.message||'连接检测通过')}catch(error){await loadStorageSources61();renderStorageSources61();toast(error.message||error)}};
  window.defaultStorageSource61=async id=>{try{await api(`/api/v61/storage-sources/${id}/default`,{method:'POST'});await loadStorageSources61();renderStorageSources61();toast('默认保存位置已更新')}catch(error){toast(error.message||error)}};
  window.toggleStorageSource61=async(id,enabled)=>{try{await api(`/api/v61/storage-sources/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})});await loadStorageSources61();renderStorageSources61()}catch(error){toast(error.message||error)}};
  window.deleteStorageSource61=async id=>{if(!confirm('只允许删除未被素材引用的存储源。确认删除该配置？'))return;try{await api(`/api/v61/storage-sources/${id}`,{method:'DELETE'});await loadStorageSources61();renderStorageSources61();toast('存储源配置已删除')}catch(error){toast(error.message||error)}};

  window.installServerMaterialImport61=function(){
    if(window.__serverMaterialImport61Installed)return true;
    window.__serverMaterialImport61Installed=true;
    const serverApi=()=>window.PlatformCore?.serverMaterialImport;
    let pollController=null;
    const taskKey=()=>`mc_server_material_import_${String(pid()||'default')}`;
    const getSavedTask=()=>{try{return localStorage.getItem(taskKey())||''}catch(_){return ''}};
    const saveTask=taskId=>{state.serverMaterialImportTaskId61=taskId||'';try{taskId?localStorage.setItem(taskKey(),taskId):localStorage.removeItem(taskKey())}catch(_){}};
    const abortPolling=()=>{if(pollController&&!pollController.signal.aborted)pollController.abort();pollController=null};
    const isAbort=error=>error?.name==='AbortError';
    const taskUrl=taskId=>`/api/v61/projects/${encodeURIComponent(pid())}/storage-imports/${encodeURIComponent(taskId)}`;
    const safeCount=value=>{const number=Number(value);return Number.isFinite(number)&&number>0?number:0};
    async function importRequest(url,options={}){
      const response=await fetch(url,options),text=await response.text();let body={};
      try{body=text?JSON.parse(text):{}}catch(_){body={detail:text}}
      if(response.ok)return body;
      const detail=body?.detail,message=typeof detail==='object'?(detail.message||detail.detail||body.message):(body.message||detail),solution=typeof detail==='object'?detail.solution:body.solution;
      throw new Error(`${message||`HTTP ${response.status}`}${solution?`\n建议：${solution}`:''}`);
    }

    function renderImportTask(task){
      const status=document.getElementById('si61Status');if(!status)return;
      const view=serverApi()?.serverImportView(task)||{},result=task?.result||{},metrics=task?.metrics||{};
      const scanned=safeCount(result.scanned_files??result.scanned??metrics.scanned_files),importable=safeCount(result.importable_images??result.importable??metrics.importable_images),duplicates=safeCount(result.duplicates??metrics.duplicates),failed=safeCount(result.failed??metrics.failed)+safeCount(result.invalid_images??metrics.invalid_images),taskId=String(task?.task_id||'').replace(/[^A-Za-z0-9_-]/g,'');
      const summary=(view.canConfirm||view.terminal)?`<div class="storage61-import-summary"><span>已扫描 <b>${scanned}</b></span><span>可导入 <b>${importable}</b></span><span>重复 <b>${duplicates}</b></span><span>失败 <b>${failed}</b></span></div>`:'';
      const quality=result.quality,classes=result.external_classes||[];
      const qualityHtml=quality?`<div class="storage61-import-quality"><b>标注数据质量</b><p>有效框 ${safeCount(quality.boxes)} · 已标注 ${safeCount(quality.annotation_status?.annotated)} · 确认空标注 ${safeCount(quality.annotation_status?.confirmed_empty)} · 缺失标注 ${safeCount(quality.annotation_status?.unannotated)} · 无效标注 ${safeCount(quality.annotation_status?.invalid)}</p><p>${Object.entries(quality.issues||{}).map(([code,n])=>`${esc(code)}：${safeCount(n)}`).join(' · ')||'未发现质量问题'}</p>${(quality.examples||[]).length?`<details><summary>查看问题示例</summary>${quality.examples.map(row=>`<p>${esc(row.object_key)} · 第 ${safeCount(row.line_number)} 行 · ${esc(row.code)}</p>`).join('')}</details>`:''}</div>`:'';
      const labels=(state.project?.labels||state.currentProject?.labels||[]),mappingHtml=view.canConfirm&&classes.length?`<div class="storage61-import-mapping"><b>外部类别 → 平台标签编码</b><p>填写现有启用标签编码，或勾选明确新建。</p>${classes.map((row,index)=>`<div class="storage61-mapping-row" data-import-class="${esc(row.class_id)}"><span>${esc(row.class_id)} · ${esc(row.name)}</span><input class="input" data-label-code value="${esc(row.target_label_code||'')}" placeholder="平台标签编码" aria-label="${esc(row.name)}的平台标签" list="si61LabelCodes"><label><input type="checkbox" data-create-label> 新建标签</label></div>`).join('')}<datalist id="si61LabelCodes">${labels.map(code=>`<option value="${esc(code)}"></option>`).join('')}</datalist></div>`:'';
      const acceptance=view.canConfirm&&quality?'<label class="field check"><input id="si61AcceptQuality" type="checkbox"> 已查看并接受质量报告（无效标注行将跳过）</label>':'';
      const confirm=view.canConfirm?`<button id="si61Confirm" class="btn mini primary" onclick="confirmStorageImport61('${taskId}')">确认建立索引</button>`:'';
      const error=(view.status==='FAILED'||view.status==='CANCELLED'||view.status==='BLOCKED_BY_ENVIRONMENT')?`<div class="alert err">${esc(task?.error||result?.error?.message||view.text||'导入失败')}</div>`:'';
      status.innerHTML=`<div class="storage61-task-head"><b>${esc(view.text||task?.status||'处理中')}</b><small>${esc(task?.status||'')} ${task?.stage?`· ${esc(task.stage)}`:''}</small></div>${summary}${qualityHtml}${mappingHtml}${acceptance}${error}${confirm?`<div class="row end">${confirm}</div>`:''}`;
      const updateConfirm=()=>{const button=document.getElementById('si61Confirm');if(button)button.disabled=[...status.querySelectorAll('[data-label-code]')].some(input=>!input.value.trim())||(Object.keys(quality?.issues||{}).length>0&&!document.getElementById('si61AcceptQuality')?.checked)};
      status.querySelectorAll('input').forEach(input=>input.addEventListener('input',updateConfirm));updateConfirm();
    }

    async function pollTask(taskId,initialTask){
      if(!taskId)return null;
      abortPolling();pollController=new AbortController();const signal=pollController.signal;
      try{return await serverApi().pollServerImport({initialTask,signal,load:()=>importRequest(taskUrl(taskId),{signal}),render:renderImportTask})}
      catch(error){if(!isAbort(error)){const status=document.getElementById('si61Status');if(status)status.innerHTML=`<div class="alert err">${esc(error?.message||error||'导入任务读取失败')}</div>`}return null}
    }

    window.setStorageImportMode61=function(mode){
      state.serverMaterialImportMode61=mode;
      document.querySelectorAll('#si61ImportShell [data-import-mode]').forEach(button=>button.classList.toggle('on',button.dataset.importMode===mode));
      document.querySelectorAll('#si61ImportShell [data-import-panel]').forEach(panel=>panel.hidden=panel.dataset.importPanel!==mode);
    };
    window.openBrowserMaterialUpload61=function(){abortPolling();closeModal();setTimeout(()=>window.openDataUpload426?.(),30)};
    window.closeStorageImport61=function(){abortPolling();return closeModal()};

    window.openStorageImport61=async function(){
      try{await loadStorageSources61()}catch(error){return toast(error.message||error)}
      const localSources=storageApi().enabledStorageSources(state.storageSources61).filter(source=>source.type==='local'),options=localSources.map(source=>`<option value="${esc(source.id)}">${esc(source.name)}</option>`).join(''),disabled=localSources.length?'':'disabled',initialMode=localSources.length?'directory_scan':'browser_upload';
      abortPolling();pollController=new AbortController();
      modal('从存储导入素材',`<div id="si61ImportShell" class="storage61-import"><div class="storage61-import-modes" role="tablist" aria-label="素材导入方式"><button class="btn" data-import-mode="browser_upload" onclick="setStorageImportMode61('browser_upload')">浏览器上传</button><button class="btn" data-import-mode="directory_scan" onclick="setStorageImportMode61('directory_scan')">服务器本地目录</button><button class="btn" data-import-mode="server_zip" onclick="setStorageImportMode61('server_zip')">服务器 ZIP</button></div><section data-import-panel="browser_upload"><div class="storage61-import-help"><b>从当前电脑上传</b><span>继续使用现有图片 / ZIP 上传流程。</span></div><button class="btn primary" onclick="openBrowserMaterialUpload61()">打开浏览器上传</button></section><section data-import-panel="directory_scan"><div class="form two"><div class="field"><label>本地存储源</label><select id="si61Source" class="select" ${disabled}>${options||'<option>暂无已启用的本地存储</option>'}</select></div><div class="field"><label>目录（相对于存储源根目录）</label><input id="si61Prefix" class="input" placeholder="例如 incoming/2026"></div></div><label class="field check"><input id="si61Recursive" type="checkbox" checked> 递归扫描子目录</label><button class="btn primary" onclick="startStorageImport61('directory_scan')" ${disabled}>开始扫描</button></section><section data-import-panel="server_zip"><div class="form two"><div class="field"><label>本地存储源</label><select id="si61ZipSource" class="select" ${disabled}>${options||'<option>暂无已启用的本地存储</option>'}</select></div><div class="field"><label>服务器 ZIP（导入目录下的相对路径）</label><input id="si61ZipPath" class="input" placeholder="例如 fire.zip"></div><div class="field"><label>解压目标（相对于存储源根目录）</label><input id="si61TargetPrefix" class="input" placeholder="例如 fire/2026"></div></div><div class="storage61-import-help"><span>目标目录已存在且非空时会拒绝导入，不会覆盖原文件。</span></div><button class="btn primary" onclick="startStorageImport61('server_zip')" ${disabled}>校验并解压扫描</button></section><div id="si61Status" class="storage61-import-status">扫描和建立索引由后台 Worker 执行；关闭此窗口不会取消任务。</div><div class="row end"><button class="btn" onclick="closeStorageImport61()">关闭</button></div></div>`,true);
      setStorageImportMode61(initialMode);
      document.getElementById('si61Status')?.insertAdjacentHTML('beforebegin','<div class="form two storage61-import-format"><div class="field"><label>数据格式</label><select id="si61Format" class="select"><option value="auto">自动识别</option><option value="yolo">YOLO 检测标注</option><option value="images">仅图片</option><option disabled>COCO / VOC（暂不支持）</option></select></div><div class="field"><label>数据集 YAML（可选，相对存储源根目录）</label><input id="si61DatasetYaml" class="input" placeholder="例如 incoming/data.yaml"></div></div>');
      const saved=getSavedTask();
      if(saved){saveTask(saved);pollTask(saved).then(task=>{if(!task&&document.getElementById('si61Status'))saveTask('')})}
    };

    window.startStorageImport61=async function(mode=state.serverMaterialImportMode61||'directory_scan'){
      const status=document.getElementById('si61Status');
      try{
        const values=mode==='server_zip'?{mode,storageSourceId:document.getElementById('si61ZipSource')?.value,zipPath:document.getElementById('si61ZipPath')?.value,targetPrefix:document.getElementById('si61TargetPrefix')?.value}:{mode,storageSourceId:document.getElementById('si61Source')?.value,prefix:document.getElementById('si61Prefix')?.value,recursive:document.getElementById('si61Recursive')?.checked!==false};
        values.importFormat=document.getElementById('si61Format')?.value||'auto';values.datasetYaml=document.getElementById('si61DatasetYaml')?.value;
        const body=serverApi().buildServerImportRequest(values),task=await importRequest(`/api/v61/projects/${encodeURIComponent(pid())}/storage-imports/scan`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),taskId=String(task.task_id||'');
        if(!taskId)throw new Error('服务器未返回导入任务 ID');saveTask(taskId);await pollTask(taskId,task);
      }catch(error){if(!isAbort(error)&&status)status.innerHTML=`<div class="alert err">${esc(error?.message||error||'创建导入任务失败')}</div>`}
    };

    window.confirmStorageImport61=async function(taskId){
      const button=document.getElementById('si61Confirm');if(button)button.disabled=true;
      try{
        const rows=[...document.querySelectorAll('[data-import-class]')].map(row=>({classId:row.dataset.importClass,code:row.querySelector('[data-label-code]')?.value,create:row.querySelector('[data-create-label]')?.checked}));
        const body=serverApi().buildImportConfirmation(rows,document.getElementById('si61AcceptQuality')?.checked);
        const task=await importRequest(`${taskUrl(taskId)}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});saveTask(taskId);const completed=await pollTask(taskId,task);
        if(completed?.status==='SUCCEEDED'){if(rows.some(row=>row.create))await window.refreshLabels414?.(false);if(state.page==='数据集')await window.reloadMaterialPage61?.();toast(`素材索引已建立：${safeCount(completed.result?.imported)} 条`)}
      }catch(error){if(!isAbort(error)){const status=document.getElementById('si61Status');if(status){status.querySelector('.storage61-confirm-error')?.remove();status.insertAdjacentHTML('beforeend',`<div class="alert err storage61-confirm-error">${esc(error?.message||error||'确认导入失败')}</div>`)}}}
      finally{if(button?.isConnected)button.disabled=false}
    };

    const previousCloseImport=window.closeModal;
    window.closeModal=async function(){if(document.getElementById('si61ImportShell'))abortPolling();return previousCloseImport?.()};
    return true;
  };

  const previousDatasetRender61=window.renderDatasets424;
  window.renderDatasets424=function(){
    const all=state.images||[],selected=state.materialSourceFilter61;
    if(selected!=='all')state.images=all.filter(row=>storageApi()?.sourceMatches(row,selected));
    try{previousDatasetRender61()}finally{state.images=all}
    const toolbar=document.querySelector('.data426-toolbar');if(toolbar&&!document.getElementById('materialSource61')){const enabled=storageApi()?.enabledStorageSources(state.storageSources61)||[];toolbar.insertAdjacentHTML('afterbegin',`<select id="materialSource61" class="select storage61-filter" onchange="state.materialSourceFilter61=this.value;renderDatasets424()"><option value="all">全部来源</option>${enabled.map(source=>`<option value="${source.id}" ${source.id===selected?'selected':''}>${esc(source.name)}</option>`).join('')}</select>`)}
    const visible=selected==='all'?all:all.filter(row=>storageApi()?.sourceMatches(row,selected));[...document.querySelectorAll('.data426-card')].forEach((card,index)=>{const row=visible[index],meta=card.querySelector('.data426-meta');if(row&&meta&&!meta.querySelector('.storage61-badge'))meta.insertAdjacentHTML('beforeend',`<span class="storage61-badge">${esc(storageApi()?.storageSourceLabel((state.storageSources61||[]).find(source=>source.id===(row.storage_source_id||'default_local')))||row.storage_type||'本地')}</span>`) });
    if(!(state.storageSources61||[]).length&&!state.storageSourcesLoading61)loadStorageSources61().then(()=>state.page==='数据集'&&renderDatasets424()).catch(()=>{});
  };

  window.openDataUpload426=async function(){
    try{await loadStorageSources61()}catch(_){}
    const sources=storageApi()?.enabledStorageSources(state.storageSources61)||[],preferred=storageApi()?.defaultStorageSource(sources);
    modal('上传数据',`<div class="storage61-upload-location"><label>保存位置</label><select id="uploadStorage61" class="select">${sources.map(source=>`<option value="${source.id}" ${source.id===preferred?.id?'selected':''}>${esc(source.name)} · ${esc(typeName61(source.type))}</option>`).join('')}</select><small>上传后仍进入统一素材池，不会创建数据集分组。</small></div><div class="upload426-choices"><button onclick="chooseUploadImages426()"><b>上传图片</b><span>支持 JPG、PNG、WEBP，可一次选择多张</span></button><button onclick="chooseUploadZip426()"><b>上传 ZIP</b><span>ZIP 导入第一版保存到平台本地存储</span></button></div><input id="up426Images" data-file426="1" class="hidden-file426" type="file" accept="image/*" multiple onchange="doUploadImages426(this)"><input id="up426Zip" data-file426="1" class="hidden-file426" type="file" accept=".zip,application/zip" onchange="doUploadZip426(this)">`,true)
  };
  window.doUploadImages426=function(input){
    const files=[...(input.files||[])];if(!files.length)return;const sourceId=document.getElementById('uploadStorage61')?.value||'default_local',form=new FormData();files.forEach(file=>form.append('files',file));form.append('dataset_id','default');form.append('storage_source_id',sourceId);const total=files.reduce((sum,file)=>sum+file.size,0),started=performance.now();closeModal();modal('图片上传',`<div class="up411"><section><b>正在上传图片</b><span>${files.length} 个文件</span></section><div class="up411-bar"><i id="up411Bar" style="width:0%"></i></div><div class="up411-line"><span id="up411Text">准备上传</span><b id="up411Pct">0%</b></div><div id="up411Result"></div></div>`,true);const xhr=new XMLHttpRequest();xhr.open('POST',`/api/projects/${pid()}/images`,true);xhr.upload.onprogress=event=>{if(!event.lengthComputable)return;const percent=event.loaded/event.total*100,bar=document.getElementById('up411Bar'),label=document.getElementById('up411Pct'),text=document.getElementById('up411Text');if(bar)bar.style.width=`${percent}%`;if(label)label.textContent=`${Math.round(percent)}%`;if(text)text.textContent=`${Math.round(event.loaded/1024)} KB / ${Math.round((event.total||total)/1024)} KB`};xhr.onerror=()=>{const out=document.getElementById('up411Result');if(out)out.innerHTML='<div class="alert err">上传失败：网络连接异常</div>'};xhr.onload=async()=>{let response={};try{response=JSON.parse(xhr.responseText||'{}')}catch(_){}const out=document.getElementById('up411Result');if(xhr.status<200||xhr.status>=300){if(out)out.innerHTML=`<div class="alert err">${esc(response.error?.detail||response.detail||xhr.responseText||'上传失败')}</div>`;return}const uploaded=response.uploaded||[];state.recentUploadedMaterials61=[...uploaded];state.images=[...uploaded,...(state.images||[])];if(out)out.innerHTML=`<div class="alert ok">成功上传 ${uploaded.length} 张${response.failed_count?`，失败 ${response.failed_count} 张`:''} · ${((performance.now()-started)/1000).toFixed(1)} 秒</div>${(response.failed||[]).map(item=>`<div class="alert warn">${esc(item.name)}：${esc(item.reason)}</div>`).join('')}<div class="upload414-decision"><div><b>本次上传 ${uploaded.length} 张素材</b><span>可以继续批量清洗或标记无需清洗。</span></div><div class="row"><button class="btn" onclick='closeModal();openBatch414("ready",${JSON.stringify(uploaded.map(row=>row.id))})'>批量无需清洗</button><button class="btn primary" onclick='closeModal();openBatch414("clean",${JSON.stringify(uploaded.map(row=>row.id))})'>批量清洗</button></div></div>`;if(state.page==='数据集')renderDatasets424()};xhr.send(form);input.value='';
  };
  window.__storageOpenUpload61=window.openDataUpload426;
  window.__storageDoUploadImages61=window.doUploadImages426;

})();


/* v42.17 final usability contracts: batch sequential annotation, translated
 * dataset labels, visible reference-label extraction, and truthful iteration UI. */
window.installUsability417=function(){
  const ready417=x=>!!(x?.annotated||x?.processing_status==='processed'||x?.cleaned_at||x?.clean_skipped);
  const label417=code=>window.PlatformCore?.materials?.labelDisplay(code,state.labels||[])||(()=>{const value=String(code||''),item=(state.labels||[]).find(x=>String(x?.code||'')===value),name=String(item?.display_name||item?.display_name_zh||'');return name&&name!==value?`${value} · ${name}`:value})();

  const baseRenderDataset417=window.renderDatasets424;
  window.renderDatasets424=function(){
    baseRenderDataset417?.();
    const modeButton=[...document.querySelectorAll('.data426-head .row > button')].find(b=>['删除','取消删除','批量操作','取消批量'].includes(b.textContent.trim()));
    if(modeButton)modeButton.textContent=state.data412DeleteMode?'取消批量':'批量操作';
    document.querySelectorAll('.data412-box em,.data426-tags span').forEach(el=>{const raw=el.textContent.trim();if(raw&&!raw.includes(' · '))el.textContent=label417(raw)});
    const previewLabels=document.querySelector('.data429-preview dd[data-labels417]');
    if(previewLabels)previewLabels.textContent=(previewLabels.dataset.labels417||'').split('|').filter(Boolean).map(label417).join('、')||'-';
    if(state.data412DeleteMode){
      const toolbar=document.querySelector('.data426-toolbar');
      if(toolbar&&!toolbar.querySelector('.batch417-action'))toolbar.insertAdjacentHTML('beforeend',state.data412Tab==='processed'?`<button class="btn primary batch417-action" onclick="openBatchAnnotation417()">批量标注</button>`:`<button class="btn batch417-action" onclick="openSelectedClean417()">清洗已选</button><button class="btn primary batch417-action" onclick="openSelectedReady417()">已选无需清洗</button>`);
    }
  };
  window.openBatchAnnotation417=function(){const ids=[...(state.data412Selected||new Set())].filter(id=>(state.images||[]).some(x=>String(x.id)===String(id)&&ready417(x)));if(!ids.length)return toast('请先选择要连续标注的已处理素材');state.annotationQueue414=ids.map(String);openAnnotation(state.annotationQueue414[0])};
  window.openSelectedClean417=function(){const ids=[...(state.data412Selected||new Set())];if(!ids.length)return toast('请先选择素材');openBatch414('clean',ids)};
  window.openSelectedReady417=function(){const ids=[...(state.data412Selected||new Set())];if(!ids.length)return toast('请先选择素材');openBatch414('ready',ids)};

  window.goAnnotation417=function(id){closeModal();setTimeout(()=>openAnnotation(id),20)};
  window.selectActiveLabel417=function(value){state.activeLabel=Number(value);renderAnnSide()};
  window.renderAnnotator=function(){
    const img=state.activeImage;if(!img)return;
    const labels=state.labels||[],hasLabels=labels.length>0,queue=(state.annotationQueue414||[String(img.id)]).map(id=>(state.images||[]).find(x=>String(x.id)===String(id))).filter(Boolean),at=Math.max(0,queue.findIndex(x=>String(x.id)===String(img.id)));
    const labelOptions=labels.map(l=>`<option value="${Number(l.class_id)}" ${Number(state.activeLabel)===Number(l.class_id)?'selected':''}>${esc(label417(l.code))}</option>`).join('');
    modal('图片标注',`<div class="ann-layout pro ann414 ann417"><aside class="ann417-queue"><header><b>连续标注</b><span>${at+1} / ${queue.length}</span></header><div>${queue.map(x=>`<button class="${String(x.id)===String(img.id)?'active':''}" onclick="goAnnotation417('${x.id}')"><img src="${x.url}" loading="lazy"><span><b>${esc(x.filename)}</b><em>${x.annotated?`${x.box_count||0} 框`:'待标注'}</em></span></button>`).join('')}</div></aside><div class="ann-work"><div class="ann-toolbar"><button id="ann414Save" class="btn primary small" onclick="saveAnn(false)">保存并继续</button><label class="ann417-label"><span>绘制标签</span><select class="select" onchange="selectActiveLabel417(this.value)">${labelOptions}</select></label><button class="btn small" onclick="goAnnotation417('${queue[Math.max(0,at-1)]?.id||img.id}')" ${at<=0?'disabled':''}>上一张</button><button class="btn small" onclick="goAnnotation417('${queue[Math.min(queue.length-1,at+1)]?.id||img.id}')" ${at>=queue.length-1?'disabled':''}>下一张</button><button class="btn small" onclick="undoAnn()">撤销</button><button class="btn small" onclick="redoAnn()">重做</button><button class="btn small danger" onclick="deleteActiveBox()">删除框</button><span class="ann414-state">${esc(img.filename)} · <b id="annSaveState">已保存</b></span><div class="ann-zoom"><button class="btn mini" onclick="zoomAnn(-0.1)">-</button><span id="zoomText">100%</span><button class="btn mini" onclick="zoomAnn(0.1)">+</button></div></div>${hasLabels?'':`<div class="ann414-emptylabel"><b>标签库为空，暂时不能画框</b><span>请先到“配置中心 → 标签管理”创建英文标签及中文对照。</span><button class="btn primary" onclick="closeModal();setPage('标签管理')">去标签管理</button></div>`}<div class="ann-canvas-wrap"><div id="annStage" class="ann-stage ${hasLabels?'':'disabled'}" style="transform:scale(${state.annZoom});transform-origin:top center"><img id="annImg" src="${img.url}"></div></div></div><aside class="side-panel ann-side"><div class="side-section"><div class="side-title">标注框 <span>${state.ann.boxes.length}</span></div><div id="annBoxes"></div></div><div class="hint-card">拖拽新建框；拖动框可移动；拖动四角可缩放；Ctrl+S 自动保存。批量模式下手动保存会进入下一张。</div></aside></div>`,true);
    const im=document.getElementById('annImg'),ready=()=>{drawBoxes();if(hasLabels)bindAnnotationEvents();renderAnnSide()};if(im?.complete)ready();else if(im)im.onload=ready;
  };
  window.renderAnnSide=function(){
    const labels=state.labels||[],box=document.getElementById('annBoxes'),boxes=state.ann?.boxes||[];
    if(box)box.innerHTML=boxes.map((b,i)=>{const item=labels.find(x=>Number(x.class_id)===Number(b.class_id));return `<div class="ann414-boxrow ${Number(state.activeBox)===i?'active':''}" onclick="state.activeBox=${i};drawBoxes();renderAnnSide()"><span><i style="background:${esc(item?.color||'#64748b')}"></i><b>${i+1}. ${esc(label417(item?.code||b.label||'unknown'))}</b></span><select class="select" onclick="event.stopPropagation()" onchange="relabelBox414(${i},this.value)">${labels.map(x=>`<option value="${Number(x.class_id)}" ${Number(x.class_id)===Number(b.class_id)?'selected':''}>${esc(label417(x.code))}</option>`).join('')}</select></div>`}).join('')||'<div class="muted">暂无框。请在顶部选择标签，然后在图片上拖拽。</div>';
  };
  const baseSaveAnnotation417=window.saveAnn;
  window.saveAnn=async function(silent=false){const savedId=String(state.activeImage?.id||''),ok=await baseSaveAnnotation417?.(silent);if(ok&&!silent){const queue=state.annotationQueue414||[],at=queue.findIndex(id=>String(id)===savedId);if(queue.length>1&&at>=0&&at<queue.length-1)setTimeout(()=>goAnnotation417(queue[at+1]),80)}return ok};

  function syncReferenceLabels417(){
    const input=document.getElementById('ai429Labels');if(!input)return;
    const previous=new Set(state.ai429ReferenceLabels417||[]),manual=String(input.value||'').split(/[,，、\n]/).map(x=>x.trim()).filter(x=>x&&!previous.has(x));
    const selected=[...(state.ai429RefSelected||new Set())],helper=window.PlatformCore?.materials?.labelsFromReferences,refs=helper?helper(state.images||[],selected):[...new Set((state.images||[]).filter(x=>selected.some(id=>String(id)===String(x.id))).flatMap(x=>x.labels||[]).filter(Boolean))].sort();state.ai429ReferenceLabels417=refs;
    input.value=[...new Set([...manual,...refs])].join('、');
    let summary=document.getElementById('ai417ReferenceLabels');if(!summary){summary=document.createElement('div');summary.id='ai417ReferenceLabels';summary.className='ai417-reference-labels';document.querySelector('.ai429-ref header')?.insertAdjacentElement('afterend',summary)}summary.innerHTML=refs.length?`<span>参考素材带出标签</span>${refs.map(x=>`<b>${esc(label417(x))}</b>`).join('')}`:'<span>选择参考素材后，将自动带出对应标签</span>';
  }
  window.toggleRef429=function(id){const key=String(id),selected=state.ai429RefSelected||(state.ai429RefSelected=new Set()),on=!selected.has(key);on?selected.add(key):selected.delete(key);const button=[...document.querySelectorAll('#ai429RefGrid button')].find(x=>String(x.dataset.imageId||'')===key);button?.classList.toggle('on',on);syncReferenceLabels417()};
  const baseSelectReference417=window.aiRefSelect412;
  window.aiRefSelect412=function(mode){baseSelectReference417?.(mode);syncReferenceLabels417()};
  const baseCreateAi417=window.createAiLabel429;
  window.createAiLabel429=function(opts={}){const result=baseCreateAi417?.(opts);window.renderAiRefs429?.();syncReferenceLabels417();return result};
  window.createAiLabel427=window.createAiLabel429;

  function projected417(){const total=window.TrainingDraftRuntime?.materialIds?.().length||0,pct=Math.max(1,Math.min(99,Number(document.getElementById('tr429ExperimentPercent')?.value||state.train429ExperimentPercent||20))),fn=window.PlatformCore?.training?.projectedRandomSplit;if(fn)return fn(total,pct);if(total<2)return{train:total,experiment:0};const experiment=Math.max(1,Math.min(total-1,Math.round(total*pct/100)));return{train:total-experiment,experiment}}
  function refreshProjected417(){const root=document.querySelector('.train429-create'),note=root?.querySelector('.train429-split-summary b'),p=projected417();if(note)note.textContent=`预计训练 ${p.train} 张 / 试验 ${p.experiment} 张`;const input=document.getElementById('tr429ExperimentPercent');if(input&&!input.dataset.bound417){input.dataset.bound417='1';input.addEventListener('input',refreshProjected417)}/* TrainingSubmitRuntime owns submit readiness; legacy projected summary must not mutate button.disabled */}
  const baseRefreshTraining417=window.refreshTrain429;
  window.refreshTrain429=function(){baseRefreshTraining417?.();setTimeout(refreshProjected417,0)};
  const baseToggleTrain417=window.toggleTrainImage429;
  window.toggleTrainImage429=function(id){baseToggleTrain417?.(id);refreshProjected417()};
  const baseShowIteration417=window.showIterationBase414;
  window.showIterationBase414=function(aid){baseShowIteration417?.(aid);const base=state.iteration414?.[aid],root=document.querySelector('.train429-create'),select=root?.querySelector('#tr429Alg'),field=select?.closest('.field'),model=root?.querySelector('#tr429Model');if(base?.version_name){if(field){select.innerHTML='';select.style.display='none';let locked=field.querySelector('.iteration417-engine');if(!locked){locked=document.createElement('div');locked.className='input iteration417-engine';field.appendChild(locked)}field.querySelector('label').textContent='训练引擎（迭代任务锁定）';locked.textContent='Ultralytics Detect'}if(model)model.textContent=`${base.version_name} · ${base.model_name||'最新模型成果'}`}refreshProjected417()};
  const baseStartTraining417=window.startAlgorithmTraining429;
  window.startAlgorithmTraining429=async function(aid){const a=(state.algorithms||[]).find(x=>String(x.id)===String(aid)),latest=a?.versions?.[0],pending=baseStartTraining417?.(aid);if(latest)state.iteration414[aid]={version_id:latest.id,version_name:latest.version_name,model_name:latest.model_name,path:latest.stored_path||latest.path||''};window.refreshTrain429?.();if(latest)showIterationBase414(aid);[30,180].forEach(delay=>setTimeout(()=>{if(latest&&!state.iteration414?.[aid]?.version_name)state.iteration414[aid]={version_id:latest.id,version_name:latest.version_name,model_name:latest.model_name,path:latest.stored_path||latest.path||''};if(latest)showIterationBase414(aid);refreshProjected417()},delay));const result=await pending;refreshProjected417();return result};
  const baseOpenSettings417=window.openTrainSettings429;
  window.openTrainSettings429=function(){const result=baseOpenSettings417?.();setTimeout(()=>{const base=state.iteration414?.[state.trainingDraft?.algorithmId],model=document.getElementById('ts428Model');if(base?.version_name&&model){const text=`${base.version_name} · ${base.model_name||'最新模型成果'}`;if(model.tagName==='SELECT'){model.innerHTML=`<option value="${esc(base.path||base.model_name||'latest')}">${esc(text)}</option>`;model.value=base.path||base.model_name||'latest'}else model.value=text;model.readOnly=true;model.disabled=true;const label=model.closest('.field')?.querySelector('label');if(label)label.textContent='迭代起点（锁定最新版本）'}},30);return result};
  window.openTrainSettings428=window.openTrainSettings429;
  const baseOpenConvert417=window.openNewConvert428;
  window.openNewConvert428=async function(...args){const result=await baseOpenConvert417?.(...args);setTimeout(()=>{const root=document.querySelector('.convert428-create'),footer=root?.querySelector('.row.end'),primary=footer?.querySelector('.btn.primary');if(footer&&primary&&!footer.querySelector('.configure417-resource'))primary.insertAdjacentHTML('beforebegin',`<button class="btn configure417-resource" onclick="closeModal();closeModal();setPage('部署资源')">配置部署资源</button>`)},20);return result};
  if(state.page==='数据集')renderDatasets424();
};

/* ============================================================
   M4: real vision providers, reviewable boxes, explicit targets
   ============================================================ */
(()=>{
  const providerNames={volcengine_ark:'火山方舟（Volcengine Ark）',aliyun_qwen:'阿里云千问（Qwen VL）',local_openai:'本地 OpenAI 兼容服务',ollama:'本地 Ollama 视觉模型'};
  const providerDefaults={volcengine_ark:'https://ark.cn-beijing.volces.com/api/v3',aliyun_qwen:'',local_openai:'http://127.0.0.1:8000/v1',ollama:'http://127.0.0.1:11434'};
  window.changeVisionProviderM4=function(){const kind=document.getElementById('mcProviderAdapter')?.value||'local_openai',url=document.getElementById('mcUrl'),key=document.getElementById('mcKeyWrap'),help=document.getElementById('mcProviderHelp');if(url&&!url.value.trim())url.value=providerDefaults[kind]||'';if(key)key.classList.toggle('hidden',kind==='ollama');if(help)help.textContent=kind==='volcengine_ark'?'填写火山方舟视觉 Endpoint ID 作为模型名称。':kind==='aliyun_qwen'?'Base URL 请按阿里云地域和工作空间填写。':kind==='ollama'?'确认 Ollama 已启动，并填写已加载的视觉模型名称。':'支持 vLLM、LM Studio 等 OpenAI Chat Completions 兼容服务。'};
  window.openModelConfigModalV35=function(id=''){
    const c=(state.modelConfigs||[]).find(x=>String(x.id)===String(id))||{},kind=c.provider_adapter||c.provider_type||'local_openai',prompt=c.annotation_prompt_template||'你是视觉目标检测标注助手。只标注标签库中的目标：{{labels_json}}。图片尺寸 {{image_width}}x{{image_height}}。{{business_instruction}} 只返回 JSON：{{output_schema}}';
    modal(id?'编辑视觉模型配置':'新增视觉模型配置',`<div class="model-m4"><div class="form two"><div class="field"><label>配置名称</label><input id="mcName" class="input" value="${esc(c.name||'')}" placeholder="例如 火山方舟自动标注"></div><div class="field"><label>模型提供商</label><select id="mcProviderAdapter" class="select" onchange="changeVisionProviderM4()">${Object.entries(providerNames).map(([v,n])=>`<option value="${v}" ${kind===v?'selected':''}>${n}</option>`).join('')}</select></div><div class="field"><label>模型名称 / Endpoint ID</label><input id="mcModel" class="input" value="${esc(c.model_name||'')}" placeholder="例如 doubao-vision-pro 或 qwen2.5vl:7b"></div><div class="field"><label>Base URL</label><input id="mcUrl" class="input" value="${esc(c.base_url||c.detect_url||providerDefaults[kind]||'')}"></div><div id="mcKeyWrap" class="field"><label>API Key</label><input id="mcApiKey" class="input" type="password" autocomplete="new-password" value="" placeholder="${c.has_api_key?'已安全保存；留空保持原值':'输入后由系统凭据管理器保存'}"></div><div class="field check"><label><input id="mcDefaultAnn" type="checkbox" ${c.default_for_annotation?'checked':''}> 设为默认自动标注模型</label></div><div class="field full"><small id="mcProviderHelp" class="model-m4-help"></small></div><div class="field full"><label>自动标注提示词</label><textarea id="mcAnnPrompt" class="textarea" rows="8">${esc(prompt)}</textarea><small>允许变量：labels_json、image_width、image_height、business_instruction、output_schema</small></div></div><details class="model-m4-advanced"><summary>高级设置</summary><div class="form two"><div class="field"><label>健康检查地址</label><input id="mcHealth" class="input" value="${esc(c.health_url||'')}"></div><div class="field"><label>备注</label><input id="mcRemark" class="input" value="${esc(c.remark||'')}"></div></div></details><div class="row end"><button class="btn" onclick="closeModal()">取消</button>${id?`<button class="btn" onclick="testModelConfigV35('${id}')">测试连接和解析</button>`:''}<button class="btn primary" onclick="saveVisionModelM4('${id}')">保存配置</button></div></div>`,true);setTimeout(changeVisionProviderM4,20)
  };
  window.saveVisionModelM4=async function(id=''){const kind=document.getElementById('mcProviderAdapter')?.value||'local_openai',name=document.getElementById('mcName')?.value.trim()||'',model=document.getElementById('mcModel')?.value.trim()||'',url=document.getElementById('mcUrl')?.value.trim()||providerDefaults[kind]||'';if(!name||!model)return toast('请填写配置名称和模型名称');if(!url)return toast('请填写该服务所在地域对应的 Base URL');const body={name,provider_type:kind,provider_adapter:kind,model_kind:'vlm',base_url:url,detect_url:url,health_url:document.getElementById('mcHealth')?.value.trim()||'',model_name:model,api_key:document.getElementById('mcApiKey')?.value||'',annotation_prompt_template:document.getElementById('mcAnnPrompt')?.value||'',default_for_annotation:!!document.getElementById('mcDefaultAnn')?.checked,remark:document.getElementById('mcRemark')?.value||'',request_mode:'openai_vision',image_field:'image',prompt_field:'prompt'};try{const saved=await api(id?`/api/v35/model-configs/${id}`:'/api/v35/model-configs',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(saved?.id){const rows=state.modelConfigs||[],i=rows.findIndex(x=>String(x.id)===String(saved.id));state.modelConfigs=i>=0?rows.map((x,n)=>n===i?saved:x):[saved,...rows]}closeModal();renderModelConfigPageV35();toast('视觉模型配置已保存')}catch(e){toast(e.message||e)}};
  window.testModelConfigV35=async function(id){try{const r=await api(`/api/v35/model-configs/${id}/test-annotation`,{method:'POST'});modal('模型连接与标注解析测试',`<div class="model-m4-test"><div class="report429-kpis"><div><span>连接</span><b>${r.reachable?'成功':'失败'}</b></div><div><span>提供商</span><b>${esc(providerNames[r.provider]||r.provider||'-')}</b></div><div><span>模型</span><b>${esc(r.model||'-')}</b></div><div><span>耗时</span><b>${Number(r.latency_ms||0)} ms</b></div></div><div class="alert ok">成功解析 ${r.parsed_boxes?.length||0} 个候选框；本次测试不会写入任何图片标注。</div><details><summary>脱敏响应预览</summary><pre class="log small-log">${esc(r.raw_preview||'')}</pre></details><div class="row end"><button class="btn" onclick="closeModal()">关闭</button></div></div>`,true)}catch(e){toast(e.message||e)}};

  function candidateBoxM4(box,image){const w=Math.max(1,Number(image?.width||1)),h=Math.max(1,Number(image?.height||1)),left=Math.max(0,Math.min(100,Number(box.x1||0)/w*100)),top=Math.max(0,Math.min(100,Number(box.y1||0)/h*100)),width=Math.max(0,Math.min(100-left,(Number(box.x2||0)-Number(box.x1||0))/w*100)),height=Math.max(0,Math.min(100-top,(Number(box.y2||0)-Number(box.y1||0))/h*100));return `<i class="ai-candidate-box" style="left:${left}%;top:${top}%;width:${width}%;height:${height}%"><em>${esc(box.label||'')} ${Math.round(Number(box.confidence||0)*100)}%</em></i>`}
  window.reviewAiLabel427=async function(id){try{const r=await api(`/api/v47/projects/${pid()}/ai-label-tasks/${id}/result`),items=r.result?.items||[];state.ai429CandidateResult=r.result||{};state.v427AiConfirm=new Set(items.filter(x=>x.status!=='failed').map(x=>String(x.image_id)));modal('AI标注结果确认',`<div class="review427 ai-review-m4"><div class="review427-top"><div><b>${esc((r.result?.labels||[]).join('、'))}</b><span>候选框仅供审核，确认后才写入正式标注</span></div></div><div class="review427-grid">${items.map(x=>{const image=(state.images||[]).find(i=>String(i.id)===String(x.image_id))||x,ok=x.status!=='failed';return `<label class="review427-card ${ok?'':'failed'}"><input type="checkbox" ${ok?'checked':'disabled'} onchange="toggleAiConfirm427('${x.image_id}',this.checked)"><div class="review427-img ai-candidate-stage"><img src="${x.url||image.url||''}" loading="lazy">${(x.boxes||[]).map(b=>candidateBoxM4(b,image)).join('')}<strong>${x.status==='failed'?'处理失败':`${(x.boxes||[]).length} 个候选框`}</strong></div><b>${esc(x.filename||'')}</b><div>${x.error?`<span class="err">${esc(x.error)}</span>`:[...new Set((x.boxes||[]).map(b=>b.label))].map(y=>`<span>${esc(y)}</span>`).join('')||'<span>未检测到目标</span>'}</div></label>`}).join('')}</div><div class="row end"><button class="btn" onclick="closeModal()">暂不应用</button><button class="btn primary" onclick="confirmAiLabel427('${id}')">确认写入标注</button></div></div>`,true)}catch(e){toast(e.message||e)}};

  const selectDeployM4=window.selectDeployTarget;
  window.selectDeployTarget=function(kind){selectDeployM4(kind);setTimeout(()=>{if(kind==='rockchip'){const select=document.getElementById('dpChip');if(select)select.innerHTML='<option value="rk3588">RK3588</option><option value="rk3568">RK3568</option>'}if(kind==='tensorrt'&&!document.getElementById('dpTargetEnvironment')){const grid=document.querySelector('.deploy-config-panel .deploy-config-grid');if(grid)grid.insertAdjacentHTML('beforeend','<div class="field full"><label>目标环境</label><input id="dpTargetEnvironment" class="input" placeholder="例如 RTX 4090 · CUDA 12.8 · TensorRT 10.9"><small>TensorRT Engine 与 GPU/CUDA/TensorRT 环境绑定，必须明确记录。</small></div>')}},0)};
  window.createDeployJob=async function(){const source=document.getElementById('dpSource')?.value||'',resource=document.getElementById('dpResource')?.value||'',target=state.deployTarget,size=parseInt(document.getElementById('dpInput')?.value||'640'),precision=document.getElementById('dpPrecision')?.value||'fp16';if(!source)return toast('请选择源模型');if(!resource)return toast('当前目标没有可用部署资源');const params={input_size:size,input_width:size,input_height:size,batch:parseInt(document.getElementById('dpBatch')?.value||'1'),opset:parseInt(document.getElementById('dpOpset')?.value||'12'),dynamic:!!document.getElementById('dpDynamic')?.checked,simplify:!!document.getElementById('dpSimplify')?.checked,precision,workspace_mb:parseInt(document.getElementById('dpWorkspace')?.value||'2048'),chip:document.getElementById('dpChip')?.value||'',soc_version:document.getElementById('dpSoc')?.value||'',atlas_product:document.getElementById('dpAtlasProduct')?.value||'',target_environment:document.getElementById('dpTargetEnvironment')?.value.trim()||'',input_name:document.getElementById('dpInputName')?.value||'images',precision_mode:document.getElementById('dpPrecisionMode')?.value||'',aipp_enabled:!!document.getElementById('dpAipp')?.checked,aipp_config:document.getElementById('dpAippConfig')?.value||'',pixel_format:document.getElementById('dpPixel')?.value||'rgb',scale:document.getElementById('dpScale')?.value||'0.0039216,0.0039216,0.0039216',mean:document.getElementById('dpMean')?.value||'0,0,0',num_core:parseInt(document.getElementById('dpCore')?.value||'1'),calibration_method:document.getElementById('dpCaliMethod')?.value||''};if(target==='ascend'&&!params.soc_version)return toast('华为 Atlas 必须填写 SoC Version');if(target==='rockchip'&&!['rk3588','rk3568'].includes(params.chip))return toast('请选择 RK3588 或 RK3568');if(target==='tensorrt'&&!params.target_environment)return toast('请填写目标 GPU、CUDA 和 TensorRT 环境');const body={source_id:source,target,resource_id:resource,params,dataset_id:document.getElementById('dpDataset')?.value||state.datasetId||'default',calibration_split:document.getElementById('dpCaliSplit')?.value||'train',calibration_count:parseInt(document.getElementById('dpCaliCount')?.value||'100')};try{await api(`/api/v39/projects/${pid()}/deploy/jobs`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});state.deployPresetSourceId='';await window.loadDeployData(true);window.renderDeployCenter();toast('真实转换任务已创建')}catch(e){toast(e.message||e)}};
  window.__m4OpenModelConfig=window.openModelConfigModalV35;
  window.__m4TestModelConfig=window.testModelConfigV35;
  window.__m4ReviewCandidates=window.reviewAiLabel427;
  window.__m4CreateDeployJob=window.createDeployJob;
})();

// ===== v26 overrides: 飞桨COCO评估开关 + 训练页无侵入轮询 =====
(function(){
  function trainJobRowsHtml(){
    return (state.jobs||[]).map(j=>`<tr><td><div class="item-title">${esc(j.algorithm_name||j.id)}</div><div class="item-sub">${esc(j.framework||'')} · ${esc(j.run_name||'')}</div></td><td><span class="pill ${statusPillClass(j.status)}">${esc(j.status_text||statusName(j.status))}</span><div class="item-sub">${esc(j.message||'')}</div></td><td>${renderJobProgress(j)}</td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td><div class="row"><button class="btn small" onclick="showLog('${j.id}')">日志</button><button class="btn small danger" onclick="stopJob('${j.id}')">停止</button><button class="btn small danger" onclick="deleteJob('${j.id}')">删除</button></div></td></tr>`).join('')||'<tr><td colspan="5">暂无训练任务</td></tr>';
  }
  window.updateTrainingJobTable=function(){
    const body=$('#trainJobRows');
    if(body) body.innerHTML=trainJobRowsHtml();
    const hint=$('#trainPollHint');
    if(hint) hint.textContent='任务状态自动刷新中，不刷新左侧表单';
    const live=$('#trainLiveBadge');
    if(live){
      const n=(state.jobs||[]).filter(j=>['queued','running','waiting','pending'].includes(j.status)).length;
      live.textContent=n?`运行中 ${n}`:'无运行任务';
      live.className='pill '+(n?'warn':'ok');
    }
  };
  window.refreshJobsOnly=async function(){
    const rows=await safe(api(`/api/projects/${pid()}/jobs`));
    if(Array.isArray(rows)) state.jobs=rows;
    updateTrainingJobTable();
    if(state.activeLogJob) await pollActiveLog();
  };

  renderTraining=function(){
    const rec=state.rec?.recommendation||{};
    $('#view').innerHTML=`<div class="grid2"><section class="panel"><div class="panel-head"><div><div class="panel-title">创建训练任务</div><div class="subline">训练算法从当前训练资源实时读取。任务状态自动刷新，但不会重绘左侧表单，避免你选择时被打断。</div></div><span class="pill ok">推荐 ${esc(rec.model||'yolo11n.pt')} / ${esc(rec.device||'cpu')}</span></div><div class="panel-body"><div class="train-tabs"><button class="on">基础配置</button><button onclick="document.getElementById('advCfg').classList.toggle('hidden')">展开/收起进阶配置</button></div><div class="form two"><div class="field"><label>训练数据集</label><select class="select" id="trainDataset">${state.datasets.map(d=>`<option value="${d.id}" ${d.id===state.datasetId?'selected':''}>${esc(d.name)}（${d.images}图）</option>`).join('')}</select></div><div class="field"><label>训练资源</label><select class="select" id="target" onchange="fillTrain()">${state.targets.map(t=>`<option value="${t.id}">${esc(t.name)} / ${t.framework==='paddle'?'飞桨':t.type==='server'?'服务器':'Ultralytics'}</option>`).join('')}</select></div><div class="field"><label>训练算法</label><select class="select" id="alg" onchange="applyAlg()"></select><div id="algMeta" class="item-sub"></div></div><div class="field"><label>基础模型权重</label><select class="select" id="model"></select><div id="modelMeta" class="item-sub"></div></div><div class="field"><label>训练轮次 ${helpIcon('epochs')}</label><input class="input" id="epochs" value="${rec.epochs||20}"></div><div class="field"><label>图片尺寸 ${helpIcon('imgsz')}</label><input class="input" id="imgsz" value="${rec.imgsz||640}"></div><div class="field"><label>批大小 ${helpIcon('batch')}</label><input class="input" id="batch" value="${rec.batch||4}"></div><div class="field"><label>训练设备 ${helpIcon('device')}</label><input class="input" id="device" value="${rec.device||'cpu'}"></div></div><div id="advCfg" class="form two adv hidden"><div class="field"><label>早停轮数 ${helpIcon('patience')}</label><input class="input" id="patience" value="100"></div><div class="field"><label>数据加载进程 ${helpIcon('workers')}</label><input class="input" id="workers" value="0"></div><div class="field"><label>优化器 ${helpIcon('optimizer')}</label><select class="select" id="optimizer"><option value="auto">auto</option><option value="SGD">SGD</option><option value="Adam">Adam</option><option value="AdamW">AdamW</option><option value="NAdam">NAdam</option><option value="RAdam">RAdam</option><option value="RMSProp">RMSProp</option></select></div><div class="field"><label>初始学习率 ${helpIcon('lr0')}</label><input class="input" id="lr0" value="0.01"></div><div class="field"><label>最终学习率比例 ${helpIcon('lrf')}</label><input class="input" id="lrf" value="0.01"></div><div class="field"><label>权重衰减 ${helpIcon('weight_decay')}</label><input class="input" id="weight_decay" value="0.0005"></div><div class="field"><label>关闭Mosaic轮数 ${helpIcon('close_mosaic')}</label><input class="input" id="close_mosaic" value="10"></div><div class="field"><label>Mosaic强度 ${helpIcon('mosaic')}</label><input class="input" id="mosaic" value="1.0"></div><div class="field"><label>缓存 ${helpIcon('cache')}</label><select class="select" id="cache"><option value="False">关闭</option><option value="ram">内存缓存</option><option value="disk">磁盘缓存</option></select></div><div class="field check"><label><input type="checkbox" id="single_cls"> 单类别训练 ${helpIcon('single_cls')}</label></div><div class="field check"><label><input type="checkbox" id="pretrained" checked> 加载所选权重（推荐） ${helpIcon('pretrained')}</label></div><div class="field check"><label><input type="checkbox" id="rect"> 矩形训练 ${helpIcon('rect')}</label></div><div class="field check"><label><input type="checkbox" id="amp" checked> AMP混合精度 ${helpIcon('amp')}</label></div><div class="field check"><label><input type="checkbox" id="cos_lr"> 余弦学习率 ${helpIcon('cos_lr')}</label></div><div class="field"><label>冻结前N层 ${helpIcon('freeze')}</label><input class="input" id="freeze" value="0"></div><div class="field check"><label><input type="checkbox" id="paddle_eval"> 飞桨训练中启用 COCO 评估</label><div class="item-sub">默认关闭。关闭时先完整训练并保存模型；开启时会在训练中输出 AP/mAP，但小数据集类别映射异常时可能中断。</div></div></div><div class="divider"></div><button class="btn primary" onclick="startTrain()">开始训练</button></div></section><section class="panel"><div class="panel-head"><div><div class="panel-title">任务列表</div><div id="trainPollHint" class="item-sub">任务状态自动刷新中，不刷新左侧表单</div></div><div class="row"><span id="trainLiveBadge" class="pill ok">无运行任务</span><button class="btn small" onclick="refreshJobsOnly().then(()=>toast('已刷新任务状态'))">刷新状态</button><button class="btn small" onclick="loadAll().then(render)">完整刷新</button></div></div><div class="panel-body"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>进度 / 倒计时</th><th>数据集</th><th>操作</th></tr></thead><tbody id="trainJobRows">${trainJobRowsHtml()}</tbody></table></div></section></div><section class="panel"><div class="panel-head"><div class="panel-title">训练日志</div><div class="row"><span id="logStateText" class="item-sub">${state.activeLogJob?'日志自动刷新中':'选择任务查看日志'}</span></div></div><div class="panel-body"><pre id="log" class="log">选择任务查看日志</pre></div></section>`;
    fillTrain();
    updateTrainingJobTable();
    if(state.activeLogJob) pollActiveLog();
  };

  const oldApplyAlgV26 = window.applyAlg;
  window.applyAlg=function(){
    if(typeof oldApplyAlgV26==='function') oldApplyAlgV26();
    const t=curTarget&&curTarget();
    const evalBox=$('#paddle_eval');
    if(evalBox){
      evalBox.disabled = !(t && t.framework==='paddle');
      if(!(t && t.framework==='paddle')) evalBox.checked=false;
    }
  };

  

  render=function(){renderNav();renderTop();renderSummary();({算法列表:renderAlgorithms,训练资源:renderResources,数据集:renderDatasets,训练任务:renderTraining,测试发布:renderTest,检测台:renderDetectBench}[state.page]||renderAlgorithms)();window.PollRegistryRuntime?.replaceTrainingJobTimer?.();};
})();

// ===== v28 overrides: 检测台/测试发布空DOM防崩溃 + 友好错误提示 =====
(function(){
  function q(id){ return document.getElementById(id); }
  function val(id, def=''){ const el=q(id); return el ? el.value : def; }
  function fileOf(id){ const el=q(id); return el && el.files ? el.files[0] : null; }
  function setHtml(id, html){ const el=q(id); if(el) el.innerHTML = html; }
  function setText(id, text){ const el=q(id); if(el) el.textContent = text; }
  function friendlyError(e){
    let msg = (e && (e.message || e.detail)) ? (e.message || e.detail) : String(e || '检测失败');
    if(msg.includes("Cannot read properties of null")){
      return '页面控件没有渲染完成或被刷新重绘了。请重新进入检测台/测试发布页后再试；v28 已修复该问题。';
    }
    if(msg.includes('Internal Server Error')){
      return '后端检测接口报错。请看下方错误详情，通常是模型路径、推理环境或模型格式不匹配。';
    }
    return msg;
  }
  function errorBox(e){
    const msg = friendlyError(e);
    return `<div class="alert err"><b>检测失败</b><div style="margin-top:6px;white-space:pre-wrap">${esc(msg)}</div></div>`;
  }
  function readyEnvFor(framework){
    const fw = framework || 'ultralytics';
    return (state.inferenceEnvs||[]).find(e=>e.framework===fw && e.status==='ready')
        || (state.inferenceEnvs||[]).find(e=>e.status==='ready')
        || null;
  }
  function modelOptionList(defaultIndex){
    const list = state.testModels || [];
    if(!list.length) return '<option value="">暂无可测试模型，请先检测训练资源或完成训练</option>';
    return list.map((m,i)=>`<option value="${i}" data-fw="${esc(m.framework||'ultralytics')}" ${i===defaultIndex?'selected':''}>${esc(m.label||m.model_name||m.path||('模型'+(i+1)))}</option>`).join('');
  }
  function selectedModel(selectId){
    const sel=q(selectId);
    if(!sel) throw new Error(`页面控件 ${selectId} 没有找到，可能是页面刚好被刷新重绘。请重新进入当前页面后再试。`);
    if(sel.value === '') throw new Error('请选择模型。若没有模型，请先在训练资源中检测 Ultralytics/飞桨环境，或先完成一次训练。');
    const idx = Number(sel.value);
    const m = (state.testModels||[])[idx];
    if(!m) throw new Error('当前选择的模型不存在，请点击“刷新模型/环境”后重新选择。');
    return {sel, m};
  }
  function modelPayload(fd, m){
    fd.append('model_name', m.model_name || m.path || '');
    fd.append('model_source', m.model_source || (m.path ? 'local' : 'project'));
    fd.append('local_path', m.path || '');
    fd.append('algorithm_id', m.algorithm_id || '');
    fd.append('version_id', m.version_id || '');
  }

  window.renderDetectionResult = function(r,title){
    const dets = r && Array.isArray(r.detections) ? r.detections : [];
    const rows = dets.map(d=>`<tr><td>${esc(d.label)}</td><td>${esc(d.confidence)}</td><td>${esc(d.x1)}, ${esc(d.y1)}, ${esc(d.x2)}, ${esc(d.y2)}</td></tr>`).join('') || '<tr><td colspan="3">无结构化明细。飞桨 PaddleDetection 模型可能只返回绘制后的检测图。</td></tr>';
    return `<div class="compare-card enhanced-result"><div class="compare-head"><div><b>${esc(title||'检测结果')}</b><div class="item-sub">${esc(r?.model||'')} · ${esc(r?.engine||'')} · ${esc(r?.elapsed_ms||0)}ms</div></div><span class="pill ${dets.length?'ok':'warn'}">${dets.length} 个结果</span></div>${r?.note?`<div class="alert warn mini-alert">${esc(r.note)}</div>`:''}${r?.image_url?`<div class="result-img-wrap"><img class="result-img" src="${r.image_url}"></div>`:''}<table class="table mini-table"><thead><tr><th>标签</th><th>置信度</th><th>坐标</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  };

  window.benchPredictOne = async function(selectId,file,conf){
    if(!file) throw new Error('请选择测试图片');
    const {sel,m} = selectedModel(selectId);
    const fw = m.framework || sel.selectedOptions?.[0]?.dataset?.fw || 'ultralytics';
    const env = readyEnvFor(fw);
    if(!env) throw new Error(`没有可用的${fw==='paddle'?'飞桨':'Ultralytics'}检测环境，请先到“训练资源”里检测并启用。`);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('conf', conf || 0.25);
    fd.append('inference_framework', fw);
    fd.append('inference_env_id', env.id || '');
    modelPayload(fd, m);
    const r = await api(`/api/v12/projects/${pid()}/predict`, {method:'POST', body:fd});
    return {r,m,env};
  };
  // 覆盖同名全局绑定，避免旧函数继续读 null.value。
  try { benchPredictOne = window.benchPredictOne; } catch(e) {}

  window.benchSingle = async function(selectId){
    const out=q('benchResult');
    const file=fileOf('benchFile');
    if(!file) return toast('请选择测试图片');
    if(out) out.innerHTML='<div class="loading">检测中...</div>';
    try{
      const {r,m}=await window.benchPredictOne(selectId,file,val('benchConf','0.25'));
      if(out) out.innerHTML=renderDetectionResult(r,m.label||m.model_name||m.path||'模型检测');
    }catch(e){
      toast(friendlyError(e));
      if(out) out.innerHTML=errorBox(e);
    }
  };

  window.benchCompare = async function(){
    const out=q('benchResult');
    const file=fileOf('benchFile');
    if(!file) return toast('请选择测试图片');
    if(out) out.innerHTML='<div class="loading">两个模型检测中...</div>';
    try{
      const a=await window.benchPredictOne('benchModelA',file,val('benchConf','0.25'));
      const b=await window.benchPredictOne('benchModelB',file,val('benchConf','0.25'));
      if(out) out.innerHTML=renderDetectionResult(a.r,a.m.label||'原始模型')+renderDetectionResult(b.r,b.m.label||'新模型');
    }catch(e){
      toast(friendlyError(e));
      if(out) out.innerHTML=errorBox(e);
    }
  };

  renderDetectBench = window.renderDetectBench = function(){
    const live=(state.jobs||[]).filter(j=>['queued','running'].includes(j.status));
    const recent=(state.jobs||[]).slice(0,5);
    const modelWarn = (state.testModels||[]).length ? '' : '<div class="alert warn">当前没有可测试模型。请先在“训练资源”里检测 Ultralytics/飞桨环境，或完成一次训练任务。</div>';
    const envWarn = (state.inferenceEnvs||[]).some(e=>e.status==='ready') ? '' : '<div class="alert warn">当前没有可用检测环境。请先到“训练资源”里检测并启用 Ultralytics 或飞桨。</div>';
    $('#view').innerHTML=`<section class="panel bench-panel"><div class="panel-head"><div><div class="panel-title">检测台</div><div class="subline">独立于发布流程。支持原始模型、新模型、飞桨模型、YOLO模型同图对比。</div></div><div class="row"><button class="btn small" onclick="loadAll().then(render)">刷新模型/环境</button><button class="btn soft small" onclick="resetBench()">清空</button></div></div><div class="panel-body">${modelWarn}${envWarn}<div class="bench-layout"><div class="bench-config"><div class="form one"><div class="field"><label>原始模型 / 对照模型</label><select class="select" id="benchModelA">${modelOptionList(0)}</select></div><div class="field"><label>新模型 / 训练后模型</label><select class="select" id="benchModelB">${modelOptionList(Math.min(1,(state.testModels||[]).length-1))}</select></div><div class="field"><label>置信度</label><div class="row"><input class="input" id="benchConf" value="0.25"><button class="btn mini" onclick="var x=document.getElementById('benchConf'); if(x) x.value='0.01'">0.01</button><button class="btn mini" onclick="var x=document.getElementById('benchConf'); if(x) x.value='0.25'">0.25</button><button class="btn mini" onclick="var x=document.getElementById('benchConf'); if(x) x.value='0.5'">0.5</button></div></div><div class="field"><label>测试图片</label><input id="benchFile" type="file" accept="image/*" class="file" onchange="previewBenchImage()"></div><div class="row wrap"><button class="btn primary" onclick="benchCompare()">同图对比检测</button><button class="btn soft" onclick="benchSingle('benchModelA')">只测左侧</button><button class="btn soft" onclick="benchSingle('benchModelB')">只测右侧</button></div></div></div><div class="bench-preview"><div class="item-title">原图预览</div><div id="benchPreview" class="preview-box">选择图片后显示原图</div><div class="item-sub">建议新模型先用 0.01 低置信度看有没有学习到目标，再提高到 0.25。</div></div></div><div id="benchResult" class="compare-grid"></div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">后台训练状态</div><span class="item-sub">检测时仍可观察训练倒计时</span></div><div class="panel-body"><div class="card-list">${live.map(j=>`<div class="item"><div><div class="item-title">${esc(j.algorithm_name||j.id)}</div>${renderJobProgress(j)}</div><span class="pill ${statusPillClass(j.status)}">${esc(j.status_text||statusName(j.status))}</span></div>`).join('')||'<div class="empty">当前没有运行中的训练任务</div>'}</div>${recent.length?`<div class="divider"></div><div class="item-sub">最近任务</div><table class="table mini-table"><tbody>${recent.map(j=>`<tr><td>${esc(j.algorithm_name||j.id)}</td><td>${esc(statusName(j.status))}</td><td>${renderJobProgress(j)}</td></tr>`).join('')}</tbody></table>`:''}</div></section>`;
  };

  renderTest = window.renderTest = function(){
    const envOptions=(state.inferenceEnvs||[]).map(e=>`<option value="${esc(e.id)}" data-fw="${esc(e.framework)}" ${e.status==='ready'?'':'disabled'}>${esc(e.name)} / ${e.framework==='paddle'?'飞桨':e.framework==='ultralytics'?'Ultralytics':'服务器'}${e.status==='ready'?'':'（不可用）'}</option>`).join('');
    const modelOptions=(state.testModels||[]).map((m,i)=>`<option value="${i}" data-fw="${esc(m.framework||'ultralytics')}">${esc(m.label||m.model_name||m.path||('模型'+(i+1)))}</option>`).join('');
    $('#view').innerHTML=`<div class="grid2"><section class="panel"><div class="panel-head"><div><div class="panel-title">模型测试</div><div class="subline">单模型测试入口；需要对比时请用检测台。</div></div><button class="btn small" onclick="loadAll().then(render)">刷新环境/模型</button></div><div class="panel-body"><div class="form"><div class="field"><label>测试环境</label><select class="select" id="inferEnv" onchange="syncTestModelByEnv()">${envOptions||'<option value="">暂无可用测试环境</option>'}</select></div><div class="field"><label>测试模型</label><select class="select" id="testModel">${modelOptions||'<option value="">暂无可测试模型</option>'}</select></div><div class="field"><label>置信度</label><input id="conf" class="input" value="0.25"></div><div class="field"><label>测试图片</label><input id="predFile" type="file" accept="image/*" class="file"></div><button class="btn primary" onclick="predict()">开始测试</button><div id="predResult"></div></div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">待发布模型</div></div><div class="panel-body"><table class="table"><thead><tr><th>模型</th><th>大小</th><th>操作</th></tr></thead><tbody>${state.pending.map(m=>`<tr><td>${esc(m.name)}</td><td>${m.size_mb}MB</td><td><button class="btn small primary" onclick="assignVersion('${esc(m.name)}')">归属算法</button></td></tr>`).join('')||'<tr><td colspan="3">暂无待发布模型</td></tr>'}</tbody></table></div></section></div><section class="panel"><div class="panel-head"><div class="panel-title">测试环境状态</div></div><div class="panel-body"><div class="card-list">${(state.inferenceEnvs||[]).map(e=>`<div class="item"><div><div class="item-title">${esc(e.name)}</div><div class="item-sub">${esc(e.python_path||e.base_url||'')} · ${esc(e.note||'')}</div></div><span class="pill ${e.status==='ready'?'ok':e.status==='warning'?'warn':'err'}">${e.status==='ready'?'可用':e.status==='warning'?'需确认':'不可用'}</span></div>`).join('')||'<div class="empty">暂无测试环境，请先到训练资源里检测 Ultralytics 或配置飞桨。</div>'}</div></div></section>`;
    syncTestModelByEnv();
  };

  window.predict = async function(){
    const out=q('predResult');
    try{
      const file=fileOf('predFile');
      if(!file) return toast('请选择图片');
      const {sel,m}=selectedModel('testModel');
      const envSel=q('inferEnv');
      const selected=envSel?.selectedOptions?.[0];
      if(!selected || selected.disabled) throw new Error('请选择可用测试环境。');
      const fw=selected.dataset.fw || m.framework || 'ultralytics';
      const fd=new FormData();
      fd.append('file', file);
      fd.append('conf', val('conf','0.25'));
      fd.append('inference_framework', fw);
      fd.append('inference_env_id', envSel.value || '');
      modelPayload(fd, m);
      if(out) out.innerHTML='<div class="loading">检测中...</div>';
      const r=await api(`/api/v12/projects/${pid()}/predict`,{method:'POST',body:fd});
      if(out) out.innerHTML=renderDetectionResult(r,m.label||m.model_name||m.path||'模型测试');
    }catch(e){
      toast(friendlyError(e));
      if(out) out.innerHTML=errorBox(e);
    }
  };

  // 最终渲染入口也统一走 v28 的测试页/检测台，避免旧闭包引用旧函数。
  render = function(){
    renderNav();renderTop();renderSummary();
    ({算法列表:renderAlgorithms,训练资源:renderResources,数据集:renderDatasets,训练任务:renderTraining,测试发布:renderTest,检测台:renderDetectBench}[state.page]||renderAlgorithms)();
    window.PollRegistryRuntime?.replaceTrainingJobTimer?.();
  };
})();

// ===== v30: 导出算法包 + 检测台零结果诊断 =====
(function(){
  function q(id){return document.getElementById(id)}
  function pendingRow(m){
    const fw = m.framework || (['pdparams','pdmodel','pdiparams'].includes(m.type)?'paddle':'ultralytics');
    const tag = fw==='paddle'?'飞桨':fw==='ultralytics'?'YOLO':'模型';
    return `<tr><td><div class="item-title">${esc(m.name)}</div><div class="item-sub">${esc(tag)} · ${esc(m.type||'')} ${m.job_name?'· '+esc(m.job_name):''}</div></td><td>${m.size_mb}MB</td><td><div class="row wrap"><button class="btn small primary" onclick="assignVersion('${esc(m.name)}')">归属算法</button><button class="btn small soft" onclick="openExportModel('${esc(m.name)}')">导出包</button></div></td></tr>`;
  }
  function zeroResultAdvice(r){
    const dets = r && Array.isArray(r.detections) ? r.detections : [];
    if(dets.length) return '';
    const engine = String(r?.engine||'').toLowerCase();
    const isPaddle = engine.includes('paddle');
    return `<div class="diag-box"><b>0 个结果排查</b><div>这不一定是系统坏了，通常是模型还没学会或置信度太高。</div><ol><li>先把置信度调到 <b>0.01</b> 再测一次。</li><li>确认测试图片和训练标签一致，例如训练的是 fire/smoke，就不要拿未标该类的图测。</li><li>当前小样本飞桨模型通常需要更多数据：每类至少 50～100 张起步，烟火类建议更多。</li><li>${isPaddle?'飞桨 .pdparams 当前优先返回绘制图；如果图上也没有框，说明模型没有给出有效预测。':'YOLO 模型如果也无框，优先检查标注和数据量。'}</li></ol></div>`;
  }
  const oldRenderDetectionResult = window.renderDetectionResult;
  window.renderDetectionResult=function(r,title){
    const html = (oldRenderDetectionResult?oldRenderDetectionResult(r,title):'') || '';
    return html + zeroResultAdvice(r);
  };
  window.openExportModel=function(modelName){
    const m=(state.pending||[]).find(x=>x.name===modelName)||{};
    const isPaddle = ['pdparams','pdmodel','pdiparams'].includes(String(m.type||'').toLowerCase()) || m.framework==='paddle';
    modal('导出算法/模型包',`<div class="form"><div class="field"><label>模型</label><input class="input" value="${esc(modelName)}" disabled></div><div class="field"><label>部署/导出目标</label><select id="exportTarget" class="select"><option value="platform_package">平台验证包（模型+标签+配置+报告）</option>${isPaddle?'<option value="paddledet_weight">PaddleDetection 权重部署包（推荐）</option><option value="paddledet_infer">尝试导出 Paddle 推理模型（pdmodel/pdiparams）</option>':'<option value="ultralytics_onnx">导出 ONNX 推理包</option>'}<option value="sophon_prepare">算能/边缘盒子准备包</option></select></div><div class="field"><label>说明</label><div class="alert warn">导出包用于部署、交付、备份；它不是蒸馏。蒸馏需要单独配置教师模型、学生模型和蒸馏数据。</div></div><div class="field check"><label><input type="checkbox" id="includeReport" checked> 包含训练报告和训练日志</label></div><div class="field check"><label><input type="checkbox" id="includeLabels" checked> 包含标签列表</label></div><button class="btn primary" onclick="submitExportModel('${esc(modelName)}')">开始导出</button><div id="exportResult"></div></div>`);
  };
  window.submitExportModel=async function(modelName){
    const out=q('exportResult'); if(out) out.innerHTML='<div class="loading">正在生成导出包...</div>';
    try{
      const body={model_name:modelName,model_source:'project',deployment_target:q('exportTarget')?.value||'platform_package',include_report:!!q('includeReport')?.checked,include_dataset_labels:!!q('includeLabels')?.checked,try_convert:true};
      const r=await api(`/api/v30/projects/${pid()}/model-export`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(out) out.innerHTML=`<div class="alert ok"><b>导出完成</b><div style="margin-top:6px">${esc(r.note||'')}</div><div style="margin-top:10px"><a class="btn primary small" href="${esc(r.download_url)}">下载导出包</a></div></div>`;
      toast('导出完成');
    }catch(e){
      if(out) out.innerHTML=`<div class="alert err"><b>导出失败</b><div style="white-space:pre-wrap;margin-top:6px">${esc(e.message||e)}</div></div>`;
      toast(e.message||'导出失败');
    }
  };
  const oldRenderTest = window.renderTest;
  window.renderTest=function(){
    const envOptions=(state.inferenceEnvs||[]).map(e=>`<option value="${esc(e.id)}" data-fw="${esc(e.framework)}" ${e.status==='ready'?'':'disabled'}>${esc(e.name)} / ${e.framework==='paddle'?'飞桨':e.framework==='ultralytics'?'Ultralytics':'服务器'}${e.status==='ready'?'':'（不可用）'}</option>`).join('');
    const modelOptions=(state.testModels||[]).map((m,i)=>`<option value="${i}" data-fw="${esc(m.framework||'ultralytics')}">${esc(m.label||m.model_name||m.path||('模型'+(i+1)))}</option>`).join('');
    $('#view').innerHTML=`<div class="grid2"><section class="panel"><div class="panel-head"><div><div class="panel-title">模型测试</div><div class="subline">单模型测试入口；需要对比时请用检测台。</div></div><button class="btn small" onclick="loadAll().then(render)">刷新环境/模型</button></div><div class="panel-body"><div class="form"><div class="field"><label>测试环境</label><select class="select" id="inferEnv" onchange="syncTestModelByEnv()">${envOptions||'<option value="">暂无可用测试环境</option>'}</select></div><div class="field"><label>测试模型</label><select class="select" id="testModel">${modelOptions||'<option value="">暂无可测试模型</option>'}</select></div><div class="field"><label>置信度</label><div class="row"><input id="conf" class="input" value="0.25"><button class="btn mini" onclick="var x=document.getElementById('conf'); if(x)x.value='0.01'">0.01</button><button class="btn mini" onclick="var x=document.getElementById('conf'); if(x)x.value='0.05'">0.05</button><button class="btn mini" onclick="var x=document.getElementById('conf'); if(x)x.value='0.25'">0.25</button></div></div><div class="field"><label>测试图片</label><input id="predFile" type="file" accept="image/*" class="file"></div><button class="btn primary" onclick="predict()">开始测试</button><div id="predResult"></div></div></div></section><section class="panel"><div class="panel-head"><div><div class="panel-title">待发布/可导出模型</div><div class="subline">先检测效果，再归属算法或导出部署包。</div></div></div><div class="panel-body"><table class="table"><thead><tr><th>模型</th><th>大小</th><th>操作</th></tr></thead><tbody>${(state.pending||[]).map(pendingRow).join('')||'<tr><td colspan="3">暂无待发布模型</td></tr>'}</tbody></table></div></section></div><section class="panel"><div class="panel-head"><div class="panel-title">测试环境状态</div></div><div class="panel-body"><div class="card-list">${(state.inferenceEnvs||[]).map(e=>`<div class="item"><div><div class="item-title">${esc(e.name)}</div><div class="item-sub">${esc(e.python_path||e.base_url||'')} · ${esc(e.note||'')}</div></div><span class="pill ${e.status==='ready'?'ok':e.status==='warning'?'warn':'err'}">${e.status==='ready'?'可用':e.status==='warning'?'需确认':'不可用'}</span></div>`).join('')||'<div class="empty">暂无测试环境，请先到训练资源里检测 Ultralytics 或配置飞桨。</div>'}</div></div></section>`;
    if(typeof syncTestModelByEnv==='function') syncTestModelByEnv();
  };
  render=function(){renderNav();renderTop();renderSummary();({算法列表:renderAlgorithms,训练资源:renderResources,数据集:renderDatasets,训练任务:renderTraining,测试发布:renderTest,检测台:renderDetectBench}[state.page]||renderAlgorithms)();window.PollRegistryRuntime?.replaceTrainingJobTimer?.();};
})();

// ===== v31: PaddleDetection 结构化结果解析与低置信度调试提示 =====
(function(){
  function _esc(x){ return (window.esc ? esc(x) : String(x ?? '').replace(/[&<>"']/g, s=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[s]))); }
  function currentConf(){
    const a=document.getElementById('benchConf');
    const b=document.getElementById('conf');
    const v=(a&&a.value)|| (b&&b.value) || '0.25';
    const n=parseFloat(v); return Number.isFinite(n)?n:0.25;
  }
  window.renderDetectionResult = function(r,title){
    r = r || {};
    const dets = Array.isArray(r.detections) ? r.detections : [];
    const conf = currentConf();
    const lowConfTip = conf < 0.05 ? `<div class="alert warn mini-alert"><b>低置信度调试模式</b>：当前置信度 ${_esc(conf)}，会显示大量弱预测框，只用于判断模型有没有反应；正式验收建议切回 0.10 或 0.25。</div>` : '';
    const rows = dets.map(d=>`<tr><td>${_esc(d.label)}</td><td>${_esc(d.confidence)}</td><td>${_esc(d.x1)}, ${_esc(d.y1)}, ${_esc(d.x2)}, ${_esc(d.y2)}</td></tr>`).join('') || '<tr><td colspan="3">暂无结构化检测框。若图上也没有框，说明模型在当前阈值下没有检出目标。</td></tr>';
    const zero = !dets.length ? `<div class="diag-box"><b>没有结构化结果时怎么判断？</b><ol><li>先确认图上是否有框；没有框就是模型没检出。</li><li>如果 0.01 有很多乱框、0.25 没框，说明模型还没学稳，不是可用效果。</li><li>飞桨模型建议先用训练集原图测试，再用新图测试泛化能力。</li></ol></div>` : '';
    const note = r.note ? `<div class="alert warn mini-alert">${_esc(r.note)}</div>` : '';
    const img = r.image_url ? `<div class="result-img-wrap"><img class="result-img" src="${_esc(r.image_url)}"></div>` : '';
    return `<div class="compare-card enhanced-result"><div class="compare-head"><div><b>${_esc(title||'检测结果')}</b><div class="item-sub">${_esc(r.model||'')} · ${_esc(r.engine||'')} · ${_esc(r.elapsed_ms||0)}ms</div></div><span class="pill ${dets.length?'ok':'warn'}">${dets.length} 个结果</span></div>${lowConfTip}${note}${img}<table class="table mini-table"><thead><tr><th>标签</th><th>置信度</th><th>坐标</th></tr></thead><tbody>${rows}</tbody></table>${zero}</div>`;
  };
})();

// ===== v32: 真实导出配置 + 导出错误中文化 =====
(function(){
  const q=id=>document.getElementById(id);
  function exportTargetHelp(target){
    const map={
      platform_package:'平台验证包：用于本机检测台、算法版本归档、项目交接。一定会包含模型、标签、配置、报告。',
      paddledet_weight:'PaddleDetection 权重部署包：用于继续用 PaddleDetection 配置 + .pdparams 加载部署。',
      paddledet_infer:'Paddle 推理模型：会尝试调用 PaddleDetection tools/export_model.py 生成 pdmodel/pdiparams。',
      ultralytics_onnx:'ONNX 推理包：会使用已配置的 Ultralytics Python 环境执行 model.export(format=onnx)。',
      sophon_prepare:'算能/边缘盒子准备包：生成转换准备配置，不直接等于 bmodel，后续要用目标芯片工具链转换。'
    };
    return map[target]||'';
  }
  window.updateExportTargetConfig=function(){
    const target=q('exportTarget')?.value||'platform_package';
    const isOnnx=target==='ultralytics_onnx';
    const isSophon=target==='sophon_prepare';
    const isPaddleInfer=target==='paddledet_infer';
    const box=q('exportTargetConfig');
    if(!box)return;
    box.innerHTML=`
      <div class="alert soft">${esc(exportTargetHelp(target))}</div>
      <div class="grid2-mini">
        <div class="field"><label>输入尺寸</label><input id="exportInputSize" class="input" value="${target.startsWith('paddledet')||isSophon?'320':'640'}" placeholder="例如 320/640"></div>
        <div class="field"><label>默认置信度</label><input id="exportConfidence" class="input" value="0.25"></div>
        <div class="field"><label>部署设备</label><select id="exportDevice" class="select"><option value="cpu">CPU</option><option value="gpu">GPU</option><option value="edge">边缘设备</option></select></div>
        <div class="field"><label>精度</label><select id="exportPrecision" class="select"><option value="fp32">FP32</option><option value="fp16">FP16</option><option value="int8">INT8</option></select></div>
      </div>
      ${isOnnx?`<div class="grid2-mini"><div class="field"><label>ONNX opset</label><input id="exportOnnxOpset" class="input" value="12"></div><div class="field check"><label><input type="checkbox" id="exportOnnxDynamic"> 动态输入尺寸</label></div><div class="field check"><label><input type="checkbox" id="exportOnnxSimplify"> 简化 ONNX</label></div></div>`:''}
      ${isSophon?`<div class="grid2-mini"><div class="field"><label>目标芯片/盒子</label><select id="exportTargetChip" class="select"><option value="bm1684x">BM1684X</option><option value="bm1688">BM1688</option><option value="cv186ah">CV186AH / 算能边缘盒子</option><option value="unknown">暂不确定，先导出准备包</option></select></div><div class="field"><label>量化方式</label><select id="exportQuantization" class="select"><option value="fp32">FP32</option><option value="fp16">FP16</option><option value="int8">INT8</option></select></div></div>`:''}
      ${isPaddleInfer?`<div class="alert warn">Paddle 推理模型转换依赖训练时的 yml 配置和 PaddleDetection tools/export_model.py。即使转换失败，也会生成可下载的权重部署包和转换日志。</div>`:''}
    `;
  };
  window.openExportModel=function(modelName){
    const m=(state.pending||[]).find(x=>x.name===modelName)||{};
    const typ=String(m.type||'').toLowerCase();
    const fw=m.framework || (['pdparams','pdmodel','pdiparams'].includes(typ)?'paddle':typ==='pt'?'ultralytics':'');
    const isPaddle=fw==='paddle' || ['pdparams','pdmodel','pdiparams'].includes(typ);
    const isPt=typ==='pt';
    const opts=[`<option value="platform_package">平台验证包（模型+标签+配置+报告）</option>`];
    if(isPaddle){opts.push(`<option value="paddledet_weight">PaddleDetection 权重部署包（推荐）</option>`);opts.push(`<option value="paddledet_infer">尝试导出 Paddle 推理模型（pdmodel/pdiparams）</option>`)}
    if(isPt){opts.push(`<option value="ultralytics_onnx">导出 ONNX 推理包</option>`)}
    opts.push(`<option value="sophon_prepare">算能/边缘盒子准备包</option>`);
    modal('导出算法/模型包',`<div class="form"><div class="field"><label>模型</label><input class="input" value="${esc(modelName)}" disabled><div class="subline">识别框架：${esc(isPaddle?'飞桨 PaddleDetection':isPt?'Ultralytics YOLO':'平台模型')}</div></div><div class="field"><label>部署/导出目标</label><select id="exportTarget" class="select" onchange="updateExportTargetConfig()">${opts.join('')}</select></div><div id="exportTargetConfig"></div><div class="field check"><label><input type="checkbox" id="includeReport" checked> 包含训练报告和训练日志</label></div><div class="field check"><label><input type="checkbox" id="includeLabels" checked> 包含标签列表</label></div><div class="alert warn">导出包用于部署、交付、备份；它不是蒸馏。蒸馏需要单独配置教师模型、学生模型和蒸馏数据。</div><button class="btn primary" onclick="submitExportModel('${esc(modelName)}')">开始导出</button><div id="exportResult"></div></div>`,true);
    updateExportTargetConfig();
  };
  window.submitExportModel=async function(modelName){
    const out=q('exportResult'); if(out) out.innerHTML='<div class="loading">正在按照部署目标生成导出包...</div>';
    try{
      const target=q('exportTarget')?.value||'platform_package';
      const export_config={
        input_size: q('exportInputSize')?.value||'',
        confidence: q('exportConfidence')?.value||'0.25',
        device: q('exportDevice')?.value||'cpu',
        precision: q('exportPrecision')?.value||'fp32',
        onnx_opset: q('exportOnnxOpset')?.value||'12',
        onnx_dynamic: !!q('exportOnnxDynamic')?.checked,
        onnx_simplify: !!q('exportOnnxSimplify')?.checked,
        target_chip: q('exportTargetChip')?.value||'',
        quantization: q('exportQuantization')?.value||q('exportPrecision')?.value||'fp32'
      };
      const body={model_name:modelName,model_source:'project',deployment_target:target,export_config,include_report:!!q('includeReport')?.checked,include_dataset_labels:!!q('includeLabels')?.checked,try_convert:true};
      const r=await api(`/api/v32/projects/${pid()}/model-export`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(out) out.innerHTML=`<div class="alert ok"><b>导出完成</b><div style="margin-top:6px;white-space:pre-wrap">${esc(r.note||'')}</div>${r.conversion_ok===false?'<div class="alert warn" style="margin-top:8px">转换没有成功，但源模型包、配置和转换日志已经打包，可下载查看。</div>':''}<div style="margin-top:10px"><a class="btn primary small" href="${esc(r.download_url)}">下载导出包</a></div></div>`;
      toast('导出完成');
    }catch(e){
      if(out) out.innerHTML=`<div class="alert err"><b>导出失败</b><div style="white-space:pre-wrap;margin-top:6px">${esc(e.message||e)}</div></div>`;
      toast(e.message||'导出失败');
    }
  };
})();

// ===== v33: 视频切帧任务 + 素材库自动标注任务 =====
(function(){
  if(!navs.includes('视频切帧')){
    const idx=navs.indexOf('数据集');
    navs.splice(idx>=0?idx+1:2,0,'视频切帧');
  }
  state.videoTasks=[];
  state.prelabelTasks=[];
  state.prelabelServices=[];

  const _oldLoadRelatedV33 = loadRelated;
  loadRelated = async function(){
    await _oldLoadRelatedV33();
    if(state.project){
      state.videoTasks=(await safe(api(`/api/v33/projects/${state.project.id}/video-tasks`)))?.items||[];
      state.prelabelTasks=(await safe(api(`/api/v33/projects/${state.project.id}/prelabel-tasks`)))?.items||[];
      state.prelabelServices=await safe(api('/api/prelabel_services'))||[];
    }
  };

  function statusCls(s){return s==='done'||s==='finished'?'ok':s==='failed'?'err':s==='stopped'?'warn':'blue'}
  function taskProgress(t){
    const p=Math.max(0,Math.min(100,parseInt(t.progress||0)));
    return `<div class="progress-mini"><i style="width:${p}%"></i></div><div class="item-sub">${p}% · ${esc(t.status_text||statusName(t.status))}</div>`;
  }
  window.refreshVideoTasksOnly=async function(){
    if(!pid())return;
    state.videoTasks=(await safe(api(`/api/v33/projects/${pid()}/video-tasks`)))?.items||[];
    const body=document.getElementById('videoTaskRows');
    if(body) body.innerHTML=videoRowsHtml();
  };
  window.refreshPrelabelTasksOnly=async function(){
    if(!pid())return;
    state.prelabelTasks=(await safe(api(`/api/v33/projects/${pid()}/prelabel-tasks`)))?.items||[];
    const box=document.getElementById('prelabelTaskList');
    if(box) box.innerHTML=prelabelTaskListHtml();
  };
  function videoRowsHtml(){
    const tasks=state.videoTasks||[];
    return tasks.map(t=>`<tr><td><b>${esc(t.video_name||t.id)}</b><div class="item-sub">${esc(t.frequency_text||((t.extract_fps||0)>0?('每秒 '+t.extract_fps+' 帧'):('每 '+(t.interval_seconds||1)+' 秒 1 帧')))} · ${esc(t.created_at||'')}</div></td><td><span class="pill ${statusCls(t.status)}">${esc(t.status_text||statusName(t.status))}</span></td><td>${taskProgress(t)}</td><td>${t.extracted_frames||0} 张</td><td>${esc(t.dataset_id||'default')} / ${esc(splitName(t.split||'train'))}</td><td><div class="row"><button class="btn mini" onclick="refreshVideoTasksOnly()">刷新</button>${t.status==='running'||t.status==='queued'?`<button class="btn mini danger" onclick="stopVideoTask('${t.id}')">停止</button>`:''}</div>${t.error?`<div class="alert err mini-alert">${esc(t.error)}</div>`:''}</td></tr>`).join('')||'<tr><td colspan="6">暂无切帧任务</td></tr>';
  }
  window.renderVideoFrameTasks=function(){
    const dsOpts=(state.datasets||[]).map(d=>`<option value="${esc(d.id)}" ${d.id===state.datasetId?'selected':''}>${esc(d.name)}（${d.images||0}图）</option>`).join('');
    $('#view').innerHTML=`<div class="grid2"><section class="panel"><div class="panel-head"><div><div class="panel-title">创建视频切帧任务</div><div class="subline">上传视频后自动抽帧进入素材库，后续可标注、自动标注、训练。</div></div></div><div class="panel-body"><div class="form two"><div class="field"><label>视频文件</label><input id="videoFile" class="file" type="file" accept="video/*"></div><div class="field"><label>目标数据集</label><select id="videoDataset" class="select">${dsOpts}</select></div><div class="field"><label>切帧方式</label><select id="frameMode" class="select" onchange="toggleFrameMode()"><option value="interval">每 N 秒抽 1 帧</option><option value="fps">每秒抽 N 帧</option></select></div><div class="field" id="intervalField"><label>切帧间隔（秒）</label><input id="intervalSeconds" class="input" value="1" placeholder="例如 1 表示每秒一帧，2 表示每2秒一帧"></div><div class="field hidden" id="fpsField"><label>每秒抽帧数</label><input id="extractFps" class="input" value="1" placeholder="例如 1 表示每秒1帧，0.5表示每2秒1帧"></div><div class="field"><label>最大切帧数量</label><input id="maxFrames" class="input" value="300" placeholder="0 表示不限制"></div><div class="field"><label>素材归属</label><select id="videoSplit" class="select"><option value="train">训练集</option><option value="val">试验集</option><option value="test">评测集</option></select></div></div><div class="alert soft">建议先用每 1～2 秒 1 帧抽样，避免一个视频瞬间切出几千张重复图片。</div><button class="btn primary" onclick="startVideoFrameTask()">创建切帧任务</button><div id="videoTaskCreateResult"></div></div></section><section class="panel"><div class="panel-head"><div><div class="panel-title">切帧任务记录</div><div class="subline">任务运行后，抽出的图片会自动出现在对应数据集素材库。</div></div><button class="btn small" onclick="refreshVideoTasksOnly()">刷新任务</button></div><div class="panel-body"><table class="table"><thead><tr><th>视频</th><th>状态</th><th>进度</th><th>已抽帧</th><th>去向</th><th>操作</th></tr></thead><tbody id="videoTaskRows">${videoRowsHtml()}</tbody></table></div></section></div><section class="panel"><div class="panel-head"><div class="panel-title">使用建议</div></div><div class="panel-body"><div class="hint-card"><b>切帧不是越多越好</b><div class="item-sub">训练数据更看重多样性。大量连续帧相似度太高，会让模型过拟合。建议先按 1～2 秒一帧抽样，再人工清洗重复帧。</div></div><div class="hint-card"><b>抽帧后下一步</b><div class="item-sub">进入“数据集”素材库 → 自动标注或人工标注 → 自动划分 → 训练。</div></div></div></section>`;
  };
  window.toggleFrameMode=function(){
    const mode=document.getElementById('frameMode')?.value||'interval';
    document.getElementById('intervalField')?.classList.toggle('hidden',mode!=='interval');
    document.getElementById('fpsField')?.classList.toggle('hidden',mode!=='fps');
  };
  window.startVideoFrameTask=async function(){
    const f=document.getElementById('videoFile')?.files?.[0];
    if(!f)return toast('请选择视频文件');
    const mode=document.getElementById('frameMode')?.value||'interval';
    const fd=new FormData();
    fd.append('video',f);
    fd.append('dataset_id',document.getElementById('videoDataset')?.value||state.datasetId||'default');
    fd.append('split',document.getElementById('videoSplit')?.value||'train');
    fd.append('interval_seconds',mode==='interval'?(document.getElementById('intervalSeconds')?.value||'1'):'0');
    fd.append('extract_fps',mode==='fps'?(document.getElementById('extractFps')?.value||'1'):'0');
    fd.append('max_frames',document.getElementById('maxFrames')?.value||'0');
    const out=document.getElementById('videoTaskCreateResult'); if(out)out.innerHTML='<div class="loading">正在上传视频并创建切帧任务...</div>';
    try{
      const r=await api(`/api/v33/projects/${pid()}/video-tasks`,{method:'POST',body:fd});
      if(out)out.innerHTML=`<div class="alert ok">任务已创建：${esc(r.video_name)}。可以在右侧查看进度。</div>`;
      await refreshVideoTasksOnly();
      toast('切帧任务已创建');
    }catch(e){ if(out)out.innerHTML=`<div class="alert err">${esc(e.message||e)}</div>`; toast(e.message||'创建失败'); }
  };
  window.stopVideoTask=async function(id){
    await safe(api(`/api/v33/projects/${pid()}/video-tasks/${id}/stop`,{method:'POST'}));
    await refreshVideoTasksOnly();
    toast('已请求停止');
  };

  function selectedImagesForAutoLabel(range){
    let imgs=state.images||[];
    if(range==='unmarked')imgs=imgs.filter(i=>(i.box_count||0)===0);
    if(range==='marked')imgs=imgs.filter(i=>(i.box_count||0)>0);
    if(range==='current')imgs=imgs.filter(img=>state.imageFilter==='all'||(state.imageFilter==='marked'?(img.box_count||0)>0:state.imageFilter==='unmarked'?(img.box_count||0)===0:(img.split||'train')===state.imageFilter));
    return imgs;
  }
  function prelabelTaskListHtml(){
    const tasks=state.prelabelTasks||[];
    return `<div class="card-list">${tasks.map(t=>`<div class="item"><div><div class="item-title">${esc(t.name||'自动标注任务')}</div><div class="item-sub">标签：${esc(t.target_label||'-')} · 已处理 ${t.processed_images||0}/${t.total_images||0} 图 · 新增 ${t.boxes_added||0} 框</div>${taskProgress(t)}${t.error?`<div class="alert err mini-alert">${esc(t.error)}</div>`:''}${(t.errors||[]).length?`<div class="alert warn mini-alert">部分图片失败：${esc((t.errors||[])[0].error||'')}</div>`:''}</div><div class="row"><span class="pill ${statusCls(t.status)}">${esc(t.status_text||statusName(t.status))}</span>${t.status==='running'||t.status==='queued'?`<button class="btn mini danger" onclick="stopPrelabelTask('${t.id}')">停止</button>`:''}</div></div>`).join('')||'<div class="empty">暂无自动标注任务</div>'}</div>`;
  }
  window.openAutoLabelModal=async function(){
    state.prelabelServices=await safe(api('/api/prelabel_services'))||[];
    state.prelabelTasks=(await safe(api(`/api/v33/projects/${pid()}/prelabel-tasks`)))?.items||[];
    const svcOpts=(state.prelabelServices||[]).map(s=>`<option value="${esc(s.id)}">${esc(s.name)} · ${esc(s.target_label||'')}</option>`).join('');
    const labelList=(state.labels||[]).map(l=>`<option value="${esc(l.code||l.display_name)}">`).join('');
    modal('素材库自动标注',`<div class="form"><div class="alert soft"><b>说明</b>：这里选择的大模型/检测服务必须能返回 bbox 坐标。平台兼容 objects、detections、results、boxes 等常见返回结构。</div><div class="field"><label>大模型/预标注服务</label><select id="preSvc" class="select" onchange="togglePrelabelManual()"><option value="">临时填写接口地址</option>${svcOpts}</select></div><div id="manualPrelabelBox"><div class="field"><label>检测接口地址</label><input id="preUrl" class="input" placeholder="例如 http://127.0.0.1:9000/detect"></div><div class="grid2-mini"><div class="field"><label>请求方式</label><select id="preMode" class="select"><option value="json_base64">JSON Base64</option><option value="multipart_file">Multipart 文件上传</option></select></div><div class="field"><label>图片字段名</label><input id="preField" class="input" value="image"></div></div><div class="field check"><label><input type="checkbox" id="savePreSvc"> 保存为大模型服务</label></div><div class="field"><label>服务名称</label><input id="preSvcName" class="input" value="本地大模型检测服务"></div></div><div class="grid2-mini"><div class="field"><label>标注范围</label><select id="preRange" class="select"><option value="unmarked">仅未标注图片</option><option value="current">当前筛选结果</option><option value="all">全部图片</option><option value="marked">已标注图片</option></select></div><div class="field"><label>目标标签</label><input id="preLabel" list="preLabelList" class="input" value="${esc((state.labels&&state.labels[0]?.code)||'fire')}"><datalist id="preLabelList">${labelList}</datalist></div><div class="field"><label>置信度阈值</label><input id="preThreshold" class="input" value="0.5"></div><div class="field check"><label><input type="checkbox" id="preOverwrite"> 覆盖同标签旧框</label></div></div><button class="btn primary" onclick="startPrelabelTask()">创建自动标注任务</button><div id="prelabelRunResult"></div><div class="divider"></div><div class="panel-head flat"><div class="panel-title">自动标注任务记录</div><button class="btn mini" onclick="refreshPrelabelTasksOnly()">刷新</button></div><div id="prelabelTaskList">${prelabelTaskListHtml()}</div></div>`,true);
    togglePrelabelManual();
  };
  window.togglePrelabelManual=function(){
    const manual=!document.getElementById('preSvc')?.value;
    document.getElementById('manualPrelabelBox')?.classList.toggle('hidden',!manual);
  };
  window.startPrelabelTask=async function(){
    const out=document.getElementById('prelabelRunResult');
    const range=document.getElementById('preRange')?.value||'unmarked';
    const imgs=selectedImagesForAutoLabel(range);
    if(!imgs.length)return toast('当前范围内没有可自动标注的图片');
    let serviceId=document.getElementById('preSvc')?.value||'';
    const label=(document.getElementById('preLabel')?.value||'person').trim();
    try{
      if(!serviceId && document.getElementById('savePreSvc')?.checked){
        const svc=await api('/api/prelabel_services',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:document.getElementById('preSvcName')?.value||'大模型检测服务',detect_url:document.getElementById('preUrl')?.value||'',request_mode:document.getElementById('preMode')?.value||'json_base64',image_field:document.getElementById('preField')?.value||'image',threshold:parseFloat(document.getElementById('preThreshold')?.value||'0.5'),target_label:label})});
        serviceId=svc.id;
      }
      const body={service_id:serviceId||null,detect_url:serviceId?null:(document.getElementById('preUrl')?.value||''),request_mode:document.getElementById('preMode')?.value||'json_base64',image_field:document.getElementById('preField')?.value||'image',threshold:parseFloat(document.getElementById('preThreshold')?.value||'0.5'),target_label:label,image_ids:imgs.map(i=>i.id),overwrite:!!document.getElementById('preOverwrite')?.checked,task_name:`${label} 自动标注`};
      if(out)out.innerHTML='<div class="loading">正在创建自动标注任务...</div>';
      const r=await api(`/api/v33/projects/${pid()}/prelabel-tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(out)out.innerHTML=`<div class="alert ok">任务已创建：${esc(r.name||r.id)}，共 ${imgs.length} 张图片。</div>`;
      await refreshPrelabelTasksOnly();
      toast('自动标注任务已创建');
    }catch(e){ if(out)out.innerHTML=`<div class="alert err">${esc(e.message||e)}</div>`; toast(e.message||'自动标注创建失败'); }
  };
  window.stopPrelabelTask=async function(id){
    await safe(api(`/api/v33/projects/${pid()}/prelabel-tasks/${id}/stop`,{method:'POST'}));
    await refreshPrelabelTasksOnly();
    toast('已请求停止');
  };

  const _baseRenderDatasetsV33=renderDatasets;
  renderDatasets=function(){
    _baseRenderDatasetsV33();
    const actions=document.querySelector('.dataset-main .panel-actions');
    if(actions && !document.getElementById('autoLabelBtnV33')){
      actions.insertAdjacentHTML('beforeend',`<button id="autoLabelBtnV33" class="btn green small" onclick="openAutoLabelModal()">自动标注</button><button class="btn soft small" onclick="setPage('视频切帧')">视频切帧</button>`);
    }
  };

  render=function(){
    renderNav();renderTop();renderSummary();
    ({算法列表:renderAlgorithms,训练资源:renderResources,数据集:renderDatasets,视频切帧:renderVideoFrameTasks,训练任务:renderTraining,测试发布:renderTest,检测台:renderDetectBench}[state.page]||renderAlgorithms)();
    window.PollRegistryRuntime?.replaceTrainingJobTimer?.();
  };
})();

// ============================================================
// v34 UI/UX + persistence patch
// ============================================================
(function(){
  const APP_VERSION='42.24.0';
  const UI_STORE_KEY='mc_train_ui_state_v34';
  const lastState=(()=>{try{return JSON.parse(localStorage.getItem(UI_STORE_KEY)||'{}')}catch{return {}}})();
  state.versionInfo=null;
  state.uiReady=false;

  function saveUiState(){
    try{
      localStorage.setItem(UI_STORE_KEY, JSON.stringify({
        page: state.page,
        projectId: state.project?.id || lastState.projectId || '',
        datasetId: state.datasetId || '',
        imageFilter: state.imageFilter || 'all',
        ts: Date.now()
      }));
    }catch(e){}
  }

  function iconFor(name){
    return ({
      '工作台':'⌘','算法列表':'◇','数据集':'▣','视频切帧':'▦','自动标注':'✦',
      '训练资源':'⚙','训练任务':'▶','测试发布':'⇧','检测台':'◎'
    }[name]||'·');
  }
  const GROUPS=[
    {title:'总览',items:['工作台']},
    {title:'数据准备',items:['数据集','视频切帧','自动标注']},
    {title:'训练生产',items:['训练资源','训练任务','测试发布','检测台']},
    {title:'资产管理',items:['算法列表']},
  ];
  const RENDER_MAP=()=>({
    '工作台': renderHomeDashboard,
    '算法列表': renderAlgorithms,
    '训练资源': renderResources,
    '数据集': renderDatasets,
    '视频切帧': (typeof renderVideoFrameTasks==='function'?renderVideoFrameTasks:renderVideoPlaceholder),
    '自动标注': renderAutoLabelPage,
    '训练任务': renderTraining,
    '测试发布': renderTest,
    '检测台': (typeof renderDetectBench==='function'?renderDetectBench:renderTest)
  });

  const oldEnsureWorkspace = ensureWorkspace;
  ensureWorkspace = async function(){
    let projects = await safe(api('/api/projects')) || [];
    if(!projects.length){
      const p=await safe(api('/api/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'默认空间',description:'系统自动创建',labels:[]})}));
      if(p) projects=[p];
    }
    state.projects=projects;
    const saved=lastState.projectId || '';
    state.project=projects.find(p=>p.id===saved) || projects[0] || null;
    const restoredPage=lastState.page==='自动标注'?'自动标注及清洗':lastState.page;
    if(restoredPage && (RENDER_MAP()[restoredPage]||restoredPage==='自动标注及清洗')) state.page=restoredPage;
    if(lastState.datasetId) state.datasetId=lastState.datasetId;
    if(lastState.imageFilter) state.imageFilter=lastState.imageFilter;
    saveUiState();
  };

  const oldLoadAll = loadAll;
  loadAll = async function(){
    await oldLoadAll();
    if(!state.versionInfo) state.versionInfo = await safe(api('/api/system/version'));
    if(!state.datasetId && state.datasets[0]) state.datasetId=state.datasets[0].id;
    saveUiState();
  };


  renderNav=function(){
    const projectName=esc(state.project?.name||'默认空间');
    const ver=esc(state.versionInfo?.version||APP_VERSION);
    $('#nav').innerHTML=`
      <div class="nav-project">
        <div class="nav-project-k">当前项目</div>
        <div class="nav-project-v" title="${projectName}">${projectName}</div>
      </div>
      ${GROUPS.map(g=>`<div class="nav-group"><div class="nav-group-title">${g.title}</div>${g.items.map(n=>`
        <button class="nav-btn ${state.page===n?'active':''}" onclick="setPage('${n}')">
          <span class="nav-left"><i>${iconFor(n)}</i><b>${n}</b></span><span class="nav-arrow">›</span>
        </button>`).join('')}</div>`).join('')}
      <div class="nav-footer"><span>Version</span><b>v${ver}</b></div>`;
  };

  renderTop=function(){
    const map={
      '工作台':['总览','从数据准备到训练部署的一站式工作流'],
      '数据集':['数据准备','上传、划分、标注、质检、导出'],
      '视频切帧':['数据准备','上传视频并按任务自动抽帧'],
      '自动标注':['数据准备','选择大模型服务批量预标注素材'],
      '训练资源':['环境接入','Ultralytics / 飞桨 / 训练服务器'],
      '训练任务':['模型训练','创建任务、看进度、看日志'],
      '测试发布':['模型验证','单模型测试、发布、部署导出'],
      '检测台':['模型对比','原始模型与新模型同图检测'],
      '算法列表':['资产管理','算法版本、训练报告、模型归档']
    };
    const [crumb,sub]=map[state.page]||['畅联云算法训练',''];
    $('#crumb').textContent=crumb;
    $('#title').innerHTML=`${state.page}<span class="title-sub">${esc(sub)}</span>`;
    $('#refreshBtn').textContent='刷新数据';
    $('#refreshBtn').onclick=async()=>{await loadAll();render();toast('已刷新，页面选择已保留')};
    const right=$('.top-right');
    if(right && !$('#versionBadge')){
      right.insertAdjacentHTML('afterbegin',`<span id="versionBadge" class="version-badge">v${esc(state.versionInfo?.version||APP_VERSION)}</span>`);
    }else if($('#versionBadge')) $('#versionBadge').textContent='v'+(state.versionInfo?.version||APP_VERSION);
  };

  renderSummary=function(){
    const imgs=state.images.length;
    const ann=state.images.filter(i=>(i.box_count||0)>0).length;
    const boxes=state.images.reduce((a,b)=>a+(b.box_count||0),0);
    const ready=state.targets.filter(t=>t.status==='ready').length;
    const running=state.jobs.filter(j=>j.status==='running').length;
    const trained=state.jobs.filter(j=>['done','finished'].includes(j.status)).length;
    $('#summary').innerHTML=`
      <div class="stat accent"><div class="k">素材图片</div><div class="v">${imgs}</div><div class="s">已标注 ${ann}</div></div>
      <div class="stat"><div class="k">标注框</div><div class="v">${boxes}</div><div class="s">用于训练质检</div></div>
      <div class="stat"><div class="k">训练资源</div><div class="v">${ready}</div><div class="s">可用环境</div></div>
      <div class="stat"><div class="k">训练任务</div><div class="v">${running}/${trained}</div><div class="s">运行中 / 已完成</div></div>
      <div class="stat"><div class="k">算法版本</div><div class="v">${state.algorithms.reduce((a,b)=>a+((b.versions||[]).length),0)}</div><div class="s">可归档交付</div></div>`;
  };

  function stepCard(n,title,desc,page,btn='进入'){
    return `<div class="flow-card" onclick="setPage('${page}')"><div class="flow-no">${n}</div><div><div class="flow-title">${title}</div><div class="flow-desc">${desc}</div><button class="btn small soft">${btn}</button></div></div>`;
  }
  window.renderHomeDashboard=function(){
    const dataDir=esc(state.versionInfo?.data_dir||'');
    const recent=(state.jobs||[]).slice(0,5);
    $('#view').innerHTML=`
      <section class="hero-panel">
        <div class="hero-left"><div class="hero-k">畅联云算法训练</div><h2>数据、训练、测试、导出，一条流程跑通</h2><p>当前版本已启用持久化数据目录，刷新页面、重启服务、升级版本后会优先保留已有项目、素材、标注、训练记录。</p><div class="hero-actions"><button class="btn primary" onclick="setPage('数据集')">开始准备数据</button><button class="btn soft" onclick="setPage('训练任务')">创建训练任务</button><button class="btn" onclick="setPage('检测台')">模型对比检测</button></div></div>
        <div class="hero-right"><div class="version-big">v${esc(state.versionInfo?.version||APP_VERSION)}</div><div class="data-path" title="${dataDir}">数据目录：${dataDir||'当前程序 data 目录'}</div></div>
      </section>
      <section class="panel"><div class="panel-head"><div><div class="panel-title">推荐操作流程</div><div class="subline">按这个顺序做，页面和菜单会更清楚。</div></div></div><div class="panel-body"><div class="flow-grid">
        ${stepCard('01','准备数据集','上传图片、视频切帧、导入标注、划分训练/评测/试验集','数据集')}
        ${stepCard('02','自动/人工标注','选择大模型预标注，再人工复核关键样本','自动标注')}
        ${stepCard('03','接入训练资源','配置 Ultralytics、飞桨 PaddleDetection 或训练服务器','训练资源')}
        ${stepCard('04','创建训练任务','按数据集和算法创建训练任务，实时查看进度','训练任务')}
        ${stepCard('05','检测与发布','用检测台对比效果，再发布为算法版本或导出部署包','检测台')}
      </div></div></section>
      <section class="panel"><div class="panel-head"><div class="panel-title">最近训练任务</div><button class="btn small" onclick="setPage('训练任务')">查看全部</button></div><div class="panel-body"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>数据集</th><th>操作</th></tr></thead><tbody>${recent.map(j=>`<tr><td>${esc(j.algorithm_name||j.id)}</td><td><span class="pill ${j.status==='done'||j.status==='finished'?'ok':j.status==='failed'?'err':'warn'}">${statusName(j.status)}</span></td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td><button class="btn small" onclick="setPage('训练任务')">查看</button></td></tr>`).join('')||'<tr><td colspan="4">暂无训练任务</td></tr>'}</tbody></table></div></section>`;
  };

  window.renderAutoLabelPage=function(){
    const tasks=state.prelabelTasks||[];
    $('#view').innerHTML=`<section class="panel"><div class="panel-head"><div><div class="panel-title">自动标注</div><div class="subline">选择本地/远程大模型服务，对素材库批量生成候选标注框。</div></div><div class="row"><button class="btn primary" onclick="openAutoLabelModal()">创建自动标注任务</button><button class="btn" onclick="loadAll().then(render)">刷新</button></div></div><div class="panel-body"><div class="empty left"><b>建议流程：</b>先在“数据集”中上传图片或通过“视频切帧”生成素材，再创建自动标注任务。自动标注结果需要人工抽检，不能直接无脑进入训练。</div><div class="divider"></div><table class="table"><thead><tr><th>任务</th><th>状态</th><th>图片</th><th>新增框</th><th>说明</th></tr></thead><tbody>${tasks.map(t=>`<tr><td>${esc(t.name||t.id)}</td><td><span class="pill ${t.status==='done'?'ok':t.status==='failed'?'err':'warn'}">${esc(t.status_text||t.status)}</span></td><td>${t.done||0}/${t.total||0}</td><td>${t.boxes||0}</td><td>${esc(t.message||'-')}</td></tr>`).join('')||'<tr><td colspan="5">暂无自动标注任务</td></tr>'}</tbody></table></div></section>`;
  };
  function renderVideoPlaceholder(){
    $('#view').innerHTML='<section class="panel"><div class="panel-head"><div class="panel-title">视频切帧</div></div><div class="panel-body"><div class="empty">当前版本未加载视频切帧模块。</div></div></section>';
  }

  render=function(){
    renderNav();renderTop();renderSummary();
    const map=RENDER_MAP();
    (map[state.page]||renderHomeDashboard)();
    window.PollRegistryRuntime?.replaceTrainingJobTimer?.();
    saveUiState();
  };

  // 重新加载一次，确保 v34 的持久化状态、版本标识和新菜单生效。
  Promise.resolve().then(async()=>{if(window.__v53BootstrapOwned)return;state.page=lastState.page&&RENDER_MAP()[lastState.page]?lastState.page:'工作台';await loadAll();render();state.uiReady=true;});
})();

// ============================================================
// v35: usable config menu, model configs, prompt library, stable resource detection
// ============================================================
(function(){
  const APP_VERSION_V35='42.24.0';
  state.modelConfigs=[];
  state.promptTemplates=[];
  state.autoLabelTab='task';
  state.resourceBusy=false;

  const _v35OldLoadAll = loadAll;
  loadAll = async function(){
    await _v35OldLoadAll();
    state.modelConfigs = (await safe(api('/api/v35/model-configs')))?.items || [];
    state.promptTemplates = (await safe(api('/api/v35/prompt-templates')))?.items || [];
  };

  function v35Icon(name){return ({'工作台':'⌘','算法列表':'◇','数据集':'▣','视频切帧':'▦','自动标注':'✦','训练任务':'▶','测试发布':'⇧','检测台':'◎','训练资源':'⚙','模型配置':'◉'}[name]||'·')}
  const V35_GROUPS=[
    {title:'资产总览',items:['工作台','算法列表']},
    {title:'数据生产',items:['数据集','视频切帧','自动标注']},
    {title:'训练验证',items:['训练任务','测试发布','检测台']},
    {title:'系统配置',items:['模型配置','训练资源']},
  ];
  const v35RenderMap=()=>({
    '工作台': typeof renderHomeDashboard==='function'?renderHomeDashboard:renderAlgorithms,
    '算法列表': renderAlgorithms,
    '数据集': renderDatasets,
    '视频切帧': typeof renderVideoFrameTasks==='function'?renderVideoFrameTasks:renderDatasets,
    '自动标注': renderAutoLabelPageV35,
    '训练任务': renderTraining,
    '测试发布': renderTest,
    '检测台': typeof renderDetectBench==='function'?renderDetectBench:renderTest,
    '训练资源': renderResources,
    '模型配置': renderModelConfigPageV35,
  });

  renderNav=function(){
    const projectName=esc(state.project?.name||'默认空间');
    const ver=esc(state.versionInfo?.version||APP_VERSION_V35);
    $('#nav').innerHTML=`<div class="nav-project"><div class="nav-project-k">当前项目</div><div class="nav-project-v" title="${projectName}">${projectName}</div></div>
      ${V35_GROUPS.map(g=>`<div class="nav-group"><div class="nav-group-title">${g.title}</div>${g.items.map(n=>`<button class="nav-btn ${state.page===n?'active':''}" onclick="setPage('${n}')"><span class="nav-left"><i>${v35Icon(n)}</i><b>${n}</b></span><span class="nav-arrow">›</span></button>`).join('')}</div>`).join('')}
      <div class="nav-footer"><span>Version</span><b>v${ver}</b></div>`;
  };

  renderTop=function(){
    const map={
      '工作台':['总览',''], '算法列表':['资产管理',''], '数据集':['数据准备',''], '视频切帧':['数据准备',''], '自动标注':['数据准备',''],
      '训练任务':['模型训练',''], '测试发布':['模型验证',''], '检测台':['模型对比',''], '训练资源':['系统配置',''], '模型配置':['系统配置','本地模型、云端模型和标注提示词']
    };
    const [crumb,sub]=map[state.page]||['畅联云算法训练',''];
    $('#crumb').textContent=crumb;
    $('#title').innerHTML=`${state.page}${sub?`<span class="title-sub">${esc(sub)}</span>`:''}`;
    $('#refreshBtn').textContent='刷新';
    $('#refreshBtn').onclick=async()=>{const cur=state.page;await loadAll();state.page=cur;render();toast('已刷新')};
    const right=$('.top-right');
    if(right && !$('#versionBadge')) right.insertAdjacentHTML('afterbegin',`<span id="versionBadge" class="version-badge">v${esc(state.versionInfo?.version||APP_VERSION_V35)}</span>`);
    if($('#versionBadge')) $('#versionBadge').textContent='v'+(state.versionInfo?.version||APP_VERSION_V35);
  };

  render=function(){
    renderNav();renderTop();renderSummary();
    const map=v35RenderMap();
    (map[state.page]||map['工作台'])();
    window.PollRegistryRuntime?.replaceTrainingJobTimer?.();
    try{localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:state.page,projectId:state.project?.id||'',datasetId:state.datasetId||'',imageFilter:state.imageFilter||'all',ts:Date.now()}))}catch(e){}
  };

  function setBtnBusy(btn, busy, text){
    if(!btn)return;
    if(busy){btn.dataset.oldText=btn.innerHTML;btn.disabled=true;btn.classList.add('loading-btn');btn.innerHTML=`<span class="tiny-spinner"></span>${esc(text||'处理中')}`}
    else{btn.disabled=false;btn.classList.remove('loading-btn');if(btn.dataset.oldText)btn.innerHTML=btn.dataset.oldText}
  }
  window.detectUltra=function(){
    const root=$('#uroot')?.value.trim()||'';
    return window.ResourceDiscoveryRuntime?.detectEnvironment(root?{scope:'fast',roots:[root]}:{scope:'auto'})||toast('资源检测模块正在加载，请稍后重试');
  };
  async function refreshPaddleTrainingTargets20d(){
    const opts=await api(`/api/training_options?project_id=${pid()}`);
    state.targets=opts?.targets||[];
    return state.targets;
  }
  window.detectPaddle=async function(){
    const action=window.NavigationStability?.action?.(state.page);
    const btn=window.event?.currentTarget; setBtnBusy(btn,true,'检测中'); state.resourceBusy=true;
    try{
      const body={name:'本机飞桨',python_path:$('#ppy')?.value||'',paddledet_dir:$('#pdet')?.value||'',paddlex_dir:$('#pxdir')?.value||''};
      const box=$('#paddleTestResult'); if(box)box.textContent='正在检测 Paddle / PaddleDetection，请稍候...';
      await api('/api/paddle_env/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(action&&!action.isCurrent())return;
      const r=await api('/api/paddle_env/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(action&&!action.isCurrent())return;
      if(box)box.textContent=`paddle=${r.modules?.paddle||'-'}，PaddleDetection=${r.paddledet_exists?'存在':'未找到'}`;
      await refreshPaddleTrainingTargets20d();
      if(action&&!action.isCurrent())return;
      render(); toast('飞桨环境已启用');
    }catch(e){toast(e.message||'检测失败')}finally{state.resourceBusy=false; setBtnBusy(btn,false)}
  };
  window.quickPaddleDetect=async function(){
    const action=window.NavigationStability?.action?.(state.page);
    const btn=window.event?.currentTarget; setBtnBusy(btn,true,'扫描中');
    try{
      const r=await api('/api/paddle_env/detect',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if(action&&!action.isCurrent())return;
      const env=(r?.candidates||[])[0]; if(!env)throw new Error('未检测到飞桨环境');
      await api('/api/paddle_env/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(env)});
      if(action&&!action.isCurrent())return;
      await refreshPaddleTrainingTargets20d();
      if(action&&!action.isCurrent())return;
      render(); toast('已启用飞桨环境');
    }catch(e){toast(e.message||'一键检测失败')}finally{setBtnBusy(btn,false)}
  };

  // ---------- Model configuration ----------
  window.renderModelConfigPageV35=function(){
    const configs=state.modelConfigs||[];
    const rows=configs.map(c=>`<tr><td><b>${esc(c.name)}</b><div class="muted-line">${esc(c.model_name||c.model_kind||'')}</div></td><td>${c.provider_type==='cloud'?'云端':'本地'}</td><td>${esc(c.detect_url||c.base_url||'')}</td><td>${esc(c.request_mode||'json_base64')}</td><td><button class="btn mini" onclick="testModelConfigV35('${c.id}')">测试</button><button class="btn mini" onclick="editModelConfigV35('${c.id}')">编辑</button><button class="btn mini danger" onclick="deleteModelConfigV35('${c.id}')">删除</button></td></tr>`).join('');
    $('#view').innerHTML=`<section class="panel"><div class="panel-head"><div><div class="panel-title">模型配置</div></div><button class="btn primary small" onclick="openModelConfigModalV35()">新增模型</button></div><div class="panel-body"><table class="table"><thead><tr><th>模型</th><th>类型</th><th>接口</th><th>请求</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="5">暂无模型配置</td></tr>'}</tbody></table></div></section><section class="panel"><div class="panel-head"><div class="panel-title">模型标注库</div><button class="btn primary small" onclick="openPromptTemplateModalV35()">新增提示词</button></div><div class="panel-body">${promptTemplateListHtmlV35()}</div></section>`;
  };
  function configOptionsV35(selected=''){return (state.modelConfigs||[]).map(c=>`<option value="${esc(c.id)}" ${c.id===selected?'selected':''}>${esc(c.name)} · ${c.provider_type==='cloud'?'云端':'本地'}</option>`).join('')}
  window.openModelConfigModalV35=function(id=''){
    const c=(state.modelConfigs||[]).find(x=>x.id===id)||{};
    modal(id?'编辑模型配置':'新增模型配置',`<div class="form two"><div class="field"><label>模型名称</label><input id="mcName" class="input" value="${esc(c.name||'')}" placeholder="如：本地 Gemma 视觉检测"></div><div class="field"><label>模型类型</label><select id="mcProvider" class="select"><option value="local" ${c.provider_type!=='cloud'?'selected':''}>本地模型</option><option value="cloud" ${c.provider_type==='cloud'?'selected':''}>云端模型</option></select></div><div class="field"><label>检测接口地址</label><input id="mcUrl" class="input" value="${esc(c.detect_url||c.base_url||'')}" placeholder="http://127.0.0.1:9000/detect"></div><div class="field"><label>健康检查地址</label><input id="mcHealth" class="input" value="${esc(c.health_url||'')}" placeholder="可选"></div><div class="field"><label>模型名称/编码</label><input id="mcModel" class="input" value="${esc(c.model_name||'')}" placeholder="如 gemma4:12b"></div><div class="field"><label>请求方式</label><select id="mcMode" class="select"><option value="json_base64" ${c.request_mode!=='multipart_file'?'selected':''}>JSON Base64</option><option value="multipart_file" ${c.request_mode==='multipart_file'?'selected':''}>Multipart 文件</option></select></div><div class="field"><label>图片字段名</label><input id="mcImageField" class="input" value="${esc(c.image_field||'image')}"></div><div class="field"><label>提示词字段名</label><input id="mcPromptField" class="input" value="${esc(c.prompt_field||'prompt')}"></div><div class="field"><label>API Key</label><input id="mcApiKey" class="input" value="" placeholder="可选；留空保持原值"></div><div class="field"><label>备注</label><input id="mcRemark" class="input" value="${esc(c.remark||'')}"></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveModelConfigV35('${esc(id)}')">保存</button></div>`,true);
  };
  window.saveModelConfigV35=async function(id=''){
    const action=window.NavigationStability?.action?.(state.page);
    const body={name:$('#mcName').value,provider_type:$('#mcProvider').value,detect_url:$('#mcUrl').value,health_url:$('#mcHealth').value,model_name:$('#mcModel').value,request_mode:$('#mcMode').value,image_field:$('#mcImageField').value,prompt_field:$('#mcPromptField').value,api_key:$('#mcApiKey').value,remark:$('#mcRemark').value,model_kind:'vision_detect'};
    const saved=await safe(api(id?`/api/v35/model-configs/${id}`:'/api/v35/model-configs',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));
    if(!saved||(action&&!action.isCurrent()))return;
    closeModal();await loadAll();
    if(action&&!action.isCurrent())return;
    await window.setPage?.('模型配置');toast('已保存模型配置');
  };
  window.deleteModelConfigV35=async function(id){if(!confirm('确认删除这个模型配置？'))return;const r=await safe(api(`/api/v35/model-configs/${id}`,{method:'DELETE'}));if(!r?.ok)return;state.modelConfigs=(state.modelConfigs||[]).filter(x=>String(x.id)!==String(id));render();toast('已删除')};
  window.testModelConfigV35=async function(id){const c=(state.modelConfigs||[]).find(x=>x.id===id);if(!c)return;const r=await safe(api('/api/v35/model-configs/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...c,api_key:''})}));if(r)modal('连接测试结果',`<pre class="log small-log">${esc(JSON.stringify(r,null,2))}</pre>`,true)};

  function promptTemplateListHtmlV35(){
    const list=state.promptTemplates||[];
    return `<table class="table"><thead><tr><th>名称</th><th>框架</th><th>标签</th><th>保存格式</th><th>操作</th></tr></thead><tbody>${list.map(t=>`<tr><td><b>${esc(t.name)}</b><div class="muted-line">${esc((t.prompt||'').slice(0,64))}</div></td><td>${esc(t.framework||'common')}</td><td>${esc((t.labels||[]).join('、'))}</td><td>${esc(t.save_format||'internal')}</td><td><button class="btn mini" onclick="openPromptTemplateModalV35('${t.id}')">编辑</button><button class="btn mini danger" onclick="deletePromptTemplateV35('${t.id}')">删除</button></td></tr>`).join('')||'<tr><td colspan="5">暂无提示词模板</td></tr>'}</tbody></table>`;
  }
  window.openPromptTemplateModalV35=function(id=''){
    const t=(state.promptTemplates||[]).find(x=>x.id===id)||{};
    modal(id?'编辑模型标注模板':'新增模型标注模板',`<div class="form two"><div class="field"><label>模板名称</label><input id="ptName" class="input" value="${esc(t.name||'')}" placeholder="如：火焰烟雾检测标注"></div><div class="field"><label>关联模型</label><select id="ptModel" class="select"><option value="">不指定</option>${configOptionsV35(t.model_config_id||'')}</select></div><div class="field"><label>训练框架</label><select id="ptFramework" class="select"><option value="ultralytics" ${t.framework==='ultralytics'?'selected':''}>Ultralytics / YOLO</option><option value="paddle" ${t.framework==='paddle'?'selected':''}>飞桨 / PaddleDetection</option><option value="common" ${!t.framework||t.framework==='common'?'selected':''}>通用</option></select></div><div class="field"><label>保存格式</label><select id="ptSaveFormat" class="select"><option value="yolo" ${t.save_format==='yolo'?'selected':''}>YOLO训练格式</option><option value="paddle" ${t.save_format==='paddle'?'selected':''}>Paddle/COCO训练格式</option><option value="internal" ${!t.save_format||t.save_format==='internal'?'selected':''}>仅保存平台标注</option></select></div><div class="field"><label>目标标签，逗号分隔</label><input id="ptLabels" class="input" value="${esc((t.labels||['fire']).join(','))}"></div><div class="field"><label>置信度阈值</label><input id="ptThreshold" class="input" value="${esc(t.threshold??0.5)}"></div><div class="field wide-field"><label>提示词</label><textarea id="ptPrompt" rows="9">${esc(t.prompt||'请检测图片中的目标，返回JSON：{"objects":[{"label":"fire","confidence":0.9,"bbox":[x1,y1,x2,y2]}]}。只返回JSON，不要解释。')}</textarea></div><div class="field"><label>备注</label><input id="ptRemark" class="input" value="${esc(t.remark||'')}"></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="savePromptTemplateV35('${esc(id)}')">保存模板</button></div>`,true);
  };
  window.savePromptTemplateV35=async function(id=''){
    const labels=$('#ptLabels').value.split(/[,，\n]/).map(x=>x.trim()).filter(Boolean);
    const body={name:$('#ptName').value,model_config_id:$('#ptModel').value,framework:$('#ptFramework').value,save_format:$('#ptSaveFormat').value,labels,prompt:$('#ptPrompt').value,threshold:parseFloat($('#ptThreshold').value||'0.5'),remark:$('#ptRemark').value,output_schema:'bbox_json'};
    const item=await safe(api(id?`/api/v35/prompt-templates/${id}`:'/api/v35/prompt-templates',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));
    if(!item?.id)return;
    const current=state.promptTemplates||[],idx=current.findIndex(x=>String(x.id)===String(item.id));
    if(idx>=0){state.promptTemplates=[...current];state.promptTemplates[idx]=item}else state.promptTemplates=[item,...current];
    closeModal();render();toast('已保存模型标注模板');
  };
  window.deletePromptTemplateV35=async function(id){if(!confirm('确认删除这个模板？'))return;const r=await safe(api(`/api/v35/prompt-templates/${id}`,{method:'DELETE'}));if(!r?.ok)return;state.promptTemplates=(state.promptTemplates||[]).filter(x=>String(x.id)!==String(id));render();toast('已删除')};

  // ---------- Auto labeling ----------
  window.renderAutoLabelPageV35=function(){
    const tab=state.autoLabelTab||'task';
    const tasks=state.prelabelTasks||[];
    $('#view').innerHTML=`<section class="panel"><div class="panel-head"><div><div class="panel-title">自动标注</div></div><div class="seg small-seg"><button class="${tab==='task'?'on':''}" onclick="state.autoLabelTab='task';render()">创建任务</button><button class="${tab==='library'?'on':''}" onclick="state.autoLabelTab='library';render()">模型标注库</button></div></div><div class="panel-body">${tab==='library'?promptLibraryPanelV35():autoLabelTaskPanelV35(tasks)}</div></section>`;
  };
  function autoLabelTaskPanelV35(tasks){
    return `<div class="row end"><button class="btn primary" onclick="openAutoLabelModal()">创建自动标注任务</button><button class="btn" onclick="refreshPrelabelTasksOnly&&refreshPrelabelTasksOnly()">刷新任务</button></div><div class="divider"></div><table class="table"><thead><tr><th>任务</th><th>模型/模板</th><th>状态</th><th>进度</th><th>输出</th></tr></thead><tbody>${(tasks||[]).map(t=>`<tr><td>${esc(t.name||t.id)}</td><td>${esc(t.model_name||'-')}<div class="muted-line">${esc(t.prompt_template_name||'')}</div></td><td><span class="pill ${t.status==='done'?'ok':t.status==='failed'?'err':'warn'}">${esc(t.status_text||t.status)}</span></td><td>${t.processed_images||0}/${t.total_images||0} 图 · ${t.boxes_added||0} 框</td><td>${esc(t.export_result?.format||t.training_framework||'-')}</td></tr>`).join('')||'<tr><td colspan="5">暂无自动标注任务</td></tr>'}</tbody></table>`;
  }
  function promptLibraryPanelV35(){return `<div class="row end"><button class="btn primary" onclick="openPromptTemplateModalV35()">新增提示词模板</button><button class="btn" onclick="setPage('模型配置')">模型配置</button></div><div class="divider"></div>${promptTemplateListHtmlV35()}`}

  window.openAutoLabelModal=async function(){
    state.modelConfigs=(await safe(api('/api/v35/model-configs')))?.items||[];
    state.promptTemplates=(await safe(api('/api/v35/prompt-templates')))?.items||[];
    state.prelabelTasks=(await safe(api(`/api/v33/projects/${pid()}/prelabel-tasks`)))?.items||[];
    const labelList=(state.labels||[]).map(l=>`<option value="${esc(l.code||l.display_name)}">`).join('');
    modal('创建自动标注任务',`<div class="form"><div class="grid2-mini"><div class="field"><label>模型标注模板</label><select id="prePromptTpl" class="select" onchange="applyPrePromptTplV35()"><option value="">不使用模板</option>${(state.promptTemplates||[]).map(t=>`<option value="${esc(t.id)}">${esc(t.name)} · ${esc(t.framework||'')}</option>`).join('')}</select></div><div class="field"><label>模型配置</label><select id="preModelCfg" class="select"><option value="">临时接口</option>${configOptionsV35('')}</select></div></div><div id="manualPrelabelBox"><div class="field"><label>临时检测接口</label><input id="preUrl" class="input" placeholder="http://127.0.0.1:9000/detect"></div></div><div class="grid2-mini"><div class="field"><label>训练框架/保存格式</label><select id="preFramework" class="select"><option value="ultralytics">Ultralytics / YOLO</option><option value="paddle">飞桨 / COCO</option><option value="internal">仅平台内部标注</option></select></div><div class="field"><label>标注范围</label><select id="preRange" class="select"><option value="unmarked">仅未标注</option><option value="current">当前筛选</option><option value="all">全部图片</option><option value="marked">已标注</option></select></div><div class="field"><label>目标标签</label><input id="preLabel" list="preLabelList" class="input" value="${esc((state.labels&&state.labels[0]?.code)||'fire')}"><datalist id="preLabelList">${labelList}</datalist></div><div class="field"><label>置信度阈值</label><input id="preThreshold" class="input" value="0.5"></div><div class="field"><label>请求方式</label><select id="preMode" class="select"><option value="json_base64">JSON Base64</option><option value="multipart_file">Multipart 文件上传</option></select></div><div class="field"><label>图片字段名</label><input id="preField" class="input" value="image"></div></div><div class="field"><label>提示词</label><textarea id="prePrompt" rows="6" placeholder="选择模板后自动带出，也可以临时修改"></textarea></div><div class="field check"><label><input type="checkbox" id="preOverwrite"> 覆盖同标签旧框</label></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="startPrelabelTask()">创建任务</button></div><div id="prelabelRunResult"></div></div>`,true);
  };
  window.applyPrePromptTplV35=function(){
    const id=$('#prePromptTpl')?.value||''; const t=(state.promptTemplates||[]).find(x=>x.id===id); if(!t)return;
    if($('#preModelCfg')&&t.model_config_id)$('#preModelCfg').value=t.model_config_id;
    if($('#preFramework'))$('#preFramework').value=(t.save_format==='yolo'?'ultralytics':t.save_format)||t.framework||'internal';
    if($('#preLabel'))$('#preLabel').value=(t.labels||[])[0]||$('#preLabel').value;
    if($('#preThreshold'))$('#preThreshold').value=t.threshold??0.5;
    if($('#prePrompt'))$('#prePrompt').value=t.prompt||'';
  };
  function selectedImagesForAutoLabelV35(range){
    const imgs=state.images||[];
    if(range==='all')return imgs;
    if(range==='marked')return imgs.filter(i=>(i.box_count||0)>0);
    if(range==='current')return imgs.filter(img=>state.imageFilter==='all'||(state.imageFilter==='marked'?(img.box_count||0)>0:state.imageFilter==='unmarked'?(img.box_count||0)===0:(img.split||'train')===state.imageFilter));
    return imgs.filter(i=>(i.box_count||0)===0);
  }
  window.startPrelabelTask=async function(){
    const out=$('#prelabelRunResult');
    try{
      const range=$('#preRange')?.value||'unmarked'; const imgs=selectedImagesForAutoLabelV35(range); if(!imgs.length)throw new Error('当前范围内没有图片');
      const body={model_config_id:$('#preModelCfg')?.value||null,prompt_template_id:$('#prePromptTpl')?.value||null,detect_url:$('#preModelCfg')?.value?null:($('#preUrl')?.value||''),request_mode:$('#preMode')?.value||'json_base64',image_field:$('#preField')?.value||'image',prompt:$('#prePrompt')?.value||'',threshold:parseFloat($('#preThreshold')?.value||'0.5'),target_label:$('#preLabel')?.value||'person',image_ids:imgs.map(i=>i.id),overwrite:!!$('#preOverwrite')?.checked,task_name:`${$('#preLabel')?.value||'目标'} 自动标注`,training_framework:$('#preFramework')?.value||'internal',dataset_id:state.datasetId,include_empty:false};
      if(out)out.innerHTML='<div class="loading">正在创建任务...</div>';
      const r=await api(`/api/v35/projects/${pid()}/prelabel-tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      if(out)out.innerHTML=`<div class="alert ok">任务已创建：${esc(r.name||r.id)}</div>`;
      await refreshPrelabelTasksOnly?.(); toast('自动标注任务已创建');
    }catch(e){ if(out)out.innerHTML=`<div class="alert err">${esc(e.message||e)}</div>`; toast(e.message||'创建失败') }
  };

  // Render now if already loaded
})();

// ============================================================
// v36: source path / server URL import for images + annotated datasets
// ============================================================
(function(){
  state.sourceImportTasks = state.sourceImportTasks || [];
  const _v36LoadAll = loadAll;
  loadAll = async function(){
    await _v36LoadAll();
    if(state.project && state.datasetId){
      state.sourceImportTasks = (await safe(api(`/api/v36/projects/${pid()}/datasets/${state.datasetId}/source-import/jobs`)))?.items || [];
    }
  };

  const oldRenderTopV36 = renderTop;
  renderTop = function(){ oldRenderTopV36(); if($('#versionBadge')) $('#versionBadge').textContent='v42.24.0'; };

  window.importData=function(){
    modal('导入素材 / 标注',`<div class="form">
      <div class="seg small-seg"><button class="on" id="impZipTab" onclick="showImportTabV36('zip')">上传压缩包</button><button id="impSourceTab" onclick="showImportTabV36('source')">地址读取</button></div>
      <div id="zipImportPane">
        <div class="field"><label>选择压缩包</label><input id="importFile" type="file" class="file" accept=".zip"></div>
        <div id="importProgressWrap" class="progress-wrap hidden"><div class="progress-line"><span id="importProgressText">准备上传</span><b id="importProgressPercent">0%</b></div><div class="progress-bar"><i id="importProgressBar" style="width:0%"></i></div></div>
        <div id="importResult"></div>
        <div class="row end"><button class="btn primary" onclick="doImportData()">开始导入</button></div>
      </div>
      <div id="sourceImportPane" class="hidden">
        <div class="field"><label>本机路径或服务器URL</label><input id="sourcePathV36" class="input" placeholder="本机目录、共享目录或 https://server/dataset.zip"></div>
        <div class="grid2-mini"><div class="field"><label>来源类型</label><select id="sourceTypeV36" class="select"><option value="auto">自动识别</option><option value="local_path">本机/共享目录</option><option value="url">服务器URL</option></select></div><div class="field"><label>数据格式</label><select id="datasetKindV36" class="select"><option value="auto">自动识别</option><option value="images">普通图片</option><option value="yolo">YOLO</option><option value="coco">COCO</option><option value="voc">VOC</option></select></div></div>
        <div class="grid2-mini"><div class="field"><label>划分方式</label><select id="splitPolicyV36" class="select"><option value="annotated_train_unannotated_test">已标注进训练/评测，未标注进试验</option><option value="source">按原目录 train/val/test</option><option value="ratio">按比例划分全部图片</option></select></div><div class="field"><label>训练/评测比例</label><input id="splitRatioV36" class="input" value="0.8,0.2,0"></div></div>
        <div class="row"><button class="btn" onclick="scanSourceImportV36()">扫描</button><button class="btn primary" onclick="startSourceImportV36()">创建读取任务</button></div>
        <div id="sourceScanResultV36"></div>
        <div class="divider"></div><div class="row between"><b>读取任务</b><button class="btn mini" onclick="refreshSourceImportTasksV36()">刷新</button></div><div id="sourceTaskListV36"></div>
      </div>
    </div>`,true);
    refreshSourceImportTasksV36();
  };

  window.showImportTabV36=function(tab){
    const zip=tab==='zip';
    $('#zipImportPane')?.classList.toggle('hidden',!zip);
    $('#sourceImportPane')?.classList.toggle('hidden',zip);
    $('#impZipTab')?.classList.toggle('on',zip);
    $('#impSourceTab')?.classList.toggle('on',!zip);
  };

  function sourcePayloadV36(){
    const ratios=($('#splitRatioV36')?.value||'0.8,0.2,0').split(/[,，/]/).map(x=>parseFloat(x.trim())).filter(x=>!Number.isNaN(x));
    return {source:$('#sourcePathV36')?.value||'',source_type:$('#sourceTypeV36')?.value||'auto',dataset_kind:$('#datasetKindV36')?.value||'auto',split_policy:$('#splitPolicyV36')?.value||'annotated_train_unannotated_test',train_ratio:ratios[0]??0.8,val_ratio:ratios[1]??0.2,test_ratio:ratios[2]??0,task_name:'地址读取导入'};
  }

  window.scanSourceImportV36=async function(){
    const out=$('#sourceScanResultV36');
    try{
      if(out)out.innerHTML='<div class="loading">正在扫描来源...</div>';
      const r=await api(`/api/v36/projects/${pid()}/datasets/${state.datasetId}/source-import/scan`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sourcePayloadV36())});
      const samples=(r.samples||[]).slice(0,8).map(x=>`<div class="muted-line">${esc(x.split||'-')} · ${esc(x.name||x.path||'')}</div>`).join('');
      if(out)out.innerHTML=`<div class="import-result"><div class="stat"><div class="k">格式</div><div class="v">${esc((r.format_hints||[]).join(' / ')||'-')}</div></div><div class="stat"><div class="k">图片</div><div class="v">${r.image_count||0}</div></div><div class="stat"><div class="k">已标注估计</div><div class="v">${r.annotated_guess||0}</div></div><div class="stat"><div class="k">未标注估计</div><div class="v">${r.unannotated_guess||0}</div></div></div>${samples?`<div class="source-samples">${samples}</div>`:''}`;
    }catch(e){ if(out)out.innerHTML=`<div class="alert err">${esc(e.message||e)}</div>`; toast(e.message||'扫描失败') }
  };

  window.startSourceImportV36=async function(){
    const out=$('#sourceScanResultV36');
    try{
      if(out)out.innerHTML='<div class="loading">正在创建读取任务...</div>';
      const r=await api(`/api/v36/projects/${pid()}/datasets/${state.datasetId}/source-import/jobs`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sourcePayloadV36())});
      if(out)out.innerHTML=`<div class="alert ok">任务已创建：${esc(r.name||r.id)}</div>`;
      await refreshSourceImportTasksV36(); toast('读取任务已创建');
    }catch(e){ if(out)out.innerHTML=`<div class="alert err">${esc(e.message||e)}</div>`; toast(e.message||'创建失败') }
  };

  window.refreshSourceImportTasksV36=async function(){
    if(!state.project || !state.datasetId)return;
    const data=await safe(api(`/api/v36/projects/${pid()}/datasets/${state.datasetId}/source-import/jobs`));
    state.sourceImportTasks=data?.items||[];
    const box=$('#sourceTaskListV36');
    if(!box)return;
    box.innerHTML=`<table class="table"><thead><tr><th>来源</th><th>状态</th><th>进度</th><th>结果</th></tr></thead><tbody>${state.sourceImportTasks.map(t=>`<tr><td><b>${esc(t.name||t.id)}</b><div class="muted-line" title="${esc(t.source||'')}">${esc((t.source||'').slice(0,60))}</div></td><td><span class="pill ${t.status==='done'?'ok':t.status==='failed'?'err':'warn'}">${esc(t.status_text||t.status)}</span><div class="muted-line">${esc(t.stage||'')}</div></td><td>${t.progress||0}%</td><td>${t.status==='failed'?esc(t.error||'失败'):`${t.imported_images||t.report?.imported_images||0}图 / ${t.boxes||t.report?.boxes||0}框`}<div class="muted-line">${t.split_counts?`训练${t.split_counts.train||0} / 评测${t.split_counts.val||0} / 试验${t.split_counts.test||0}`:''}</div></td></tr>`).join('')||'<tr><td colspan="4">暂无地址读取任务</td></tr>'}</tbody></table>`;
    if(state.sourceImportTasks.some(t=>['queued','running'].includes(t.status))){
      clearTimeout(window.__sourceImportTimerV36);
      window.__sourceImportTimerV36=setTimeout(refreshSourceImportTasksV36,1800);
    }else{
      await loadRelated();
    }
  };

  // Keep the existing dataset page clean; the “导入标注” button now covers file upload and address reading.
})();

// ============================================================
// v37: page hierarchy, compact dashboard, sidebar and modal polish
// ============================================================
(function(){
  const V37_VERSION='42.24.0';
  const MENU_GROUPS=[
    {title:'资产中心',items:['工作台','算法列表']},
    {title:'数据中心',items:['数据集','视频切帧','自动标注']},
    {title:'训练中心',items:['训练任务','测试发布','检测台']},
    {title:'配置中心',items:['模型配置','训练资源']},
  ];
  const PAGE_META={
    '工作台':['首页','掌握数据、训练任务和模型资产'],
    '算法列表':['资产中心','管理算法及版本'],
    '数据集':['数据中心','素材、标注与数据划分'],
    '视频切帧':['数据中心','从视频生成训练素材'],
    '自动标注':['数据中心','使用模型批量生成标注'],
    '训练任务':['训练中心','创建并跟踪训练任务'],
    '测试发布':['训练中心','测试模型并发布版本'],
    '检测台':['训练中心','对比原始模型与训练模型'],
    '模型配置':['配置中心','管理本地与云端模型'],
    '训练资源':['配置中心','管理 Ultralytics、飞桨和训练服务器'],
  };
  const ICON_PATHS={
    '工作台':'<path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z"/>',
    '算法列表':'<path d="M8 6h13M8 12h13M8 18h13"/><circle cx="4" cy="6" r="1.4"/><circle cx="4" cy="12" r="1.4"/><circle cx="4" cy="18" r="1.4"/>',
    '数据集':'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    '视频切帧':'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3zM7 5v14M17 5v14"/>',
    '自动标注':'<path d="m12 3 1.4 4.1L17.5 8.5l-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4zM18 14l.9 2.6 2.6.9-2.6.9L18 21l-.9-2.6-2.6-.9 2.6-.9z"/>',
    '训练任务':'<path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/>',
    '测试发布':'<path d="M12 3v12M7 8l5-5 5 5M5 15v5h14v-5"/>',
    '检测台':'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    '模型配置':'<path d="M4 5h16v14H4zM8 9h8M8 13h5"/><path d="M8 19v2M16 19v2"/>',
    '训练资源':'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1V21H9.6v-.09a1.7 1.7 0 0 0-1.1-1.51 1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1-.4H3V9.6h.09A1.7 1.7 0 0 0 4.6 8.5a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1V3h4v.09A1.7 1.7 0 0 0 15.5 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.4.3.8.7 1 .9.2.4.3.8.3 1.2v1.8c0 .4-.1.8-.3 1.1-.2.4-.6.8-1 1z"/>',
  };
  function icon(name){return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON_PATHS[name]||'<circle cx="12" cy="12" r="8"/>'}</svg>`}
  function totalVersions(){return (state.algorithms||[]).reduce((n,a)=>n+((a.versions||[]).length),0)}
  function isDone(s){return ['done','finished','completed'].includes(s)}

  window.toggleSidebarV37=function(){
    document.body.classList.toggle('sidebar-collapsed');
    try{localStorage.setItem('mc_sidebar_collapsed_v37',document.body.classList.contains('sidebar-collapsed')?'1':'0')}catch(e){}
  };
  window.toggleMobileSidebarV37=function(force){
    const side=document.getElementById('sidebar'),back=document.getElementById('sideBackdrop');
    if(!side||!back)return;
    const open=typeof force==='boolean'?force:!side.classList.contains('mobile-open');
    side.classList.toggle('mobile-open',open);back.classList.toggle('show',open);
  };
  try{if(localStorage.getItem('mc_sidebar_collapsed_v37')==='1')document.body.classList.add('sidebar-collapsed')}catch(e){}

  renderNav=function(){
    const projectName=esc(state.project?.name||'默认空间');
    document.getElementById('nav').innerHTML=`<div class="nav-project"><div class="nav-project-k">当前项目</div><div class="nav-project-v" title="${projectName}">${projectName}</div></div>${MENU_GROUPS.map(g=>`<div class="nav-group"><div class="nav-group-title">${g.title}</div>${g.items.map(n=>`<button class="nav-btn ${state.page===n?'active':''}" title="${n}" onclick="setPage('${n}')"><span class="nav-left"><i>${icon(n)}</i><b>${n}</b></span><span class="nav-arrow">›</span></button>`).join('')}</div>`).join('')}<div class="nav-footer"><span>版本</span><b>v${V37_VERSION}</b></div>`;
  };

  renderTop=function(){
    const meta=PAGE_META[state.page]||['畅联云算法训练',''];
    const crumb=document.getElementById('crumb'),title=document.getElementById('title'),desc=document.getElementById('pageDesc');
    if(crumb)crumb.textContent=meta[0]; if(title)title.textContent=state.page; if(desc)desc.textContent=meta[1];
    const project=document.querySelector('#projectBadge span:last-child');if(project)project.textContent=state.project?.name||'默认空间';
    const version=document.getElementById('versionBadge');if(version)version.textContent='v'+V37_VERSION;
    const refresh=document.getElementById('refreshBtn');
    if(refresh){refresh.textContent='刷新';refresh.onclick=async function(){const old=refresh.innerHTML;refresh.disabled=true;refresh.innerHTML='<span class="tiny-spinner"></span>刷新中';const page=state.page;try{await loadAll();state.page=page;render();toast('已刷新')}finally{refresh.disabled=false;refresh.innerHTML=old}}}
  };

  renderSummary=function(){
    const box=document.getElementById('summary');if(!box)return;
    if(state.page!=='工作台'){box.classList.add('is-hidden');box.innerHTML='';return}
    box.classList.remove('is-hidden');
    const imgs=(state.images||[]).length,ann=(state.images||[]).filter(i=>(i.box_count||0)>0).length,boxes=(state.images||[]).reduce((a,b)=>a+(b.box_count||0),0);
    const running=(state.jobs||[]).filter(j=>j.status==='running'||j.status==='queued').length,done=(state.jobs||[]).filter(j=>isDone(j.status)).length,ready=(state.targets||[]).filter(t=>t.status==='ready').length;
    box.innerHTML=`<div class="stat"><div class="k">素材图片</div><div class="v">${imgs}</div><div class="s">已标注 ${ann}</div></div><div class="stat"><div class="k">标注框</div><div class="v">${boxes}</div><div class="s">当前项目</div></div><div class="stat"><div class="k">训练任务</div><div class="v">${running}</div><div class="s">运行或排队</div></div><div class="stat"><div class="k">已完成训练</div><div class="v">${done}</div><div class="s">可进入测试</div></div><div class="stat"><div class="k">算法版本</div><div class="v">${totalVersions()}</div><div class="s">资源可用 ${ready}</div></div>`;
  };

  window.renderHomeDashboard=renderHomeDashboard=function(){
    const recent=(state.jobs||[]).slice(0,6),resources=(state.targets||[]).slice(0,5);
    const taskRows=recent.map(j=>`<tr><td><b>${esc(j.algorithm_name||j.name||j.id)}</b></td><td><span class="pill ${isDone(j.status)?'ok':j.status==='failed'?'err':'warn'}">${esc(statusName(j.status))}</span></td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td><button class="btn mini" onclick="setPage('训练任务')">查看</button></td></tr>`).join('')||'<tr><td colspan="4">暂无训练任务</td></tr>';
    const resourceRows=resources.map(t=>`<div class="resource-mini-v37"><div><b>${esc(t.name)}</b><div class="item-sub">${esc(t.framework==='paddle'?'飞桨 PaddleDetection':t.framework==='ultralytics'?'Ultralytics':t.type==='server'?'训练服务器':'训练资源')}</div></div><div class="row"><i class="status-dot-v37 ${t.status==='ready'?'ok':''}"></i><span class="item-sub">${t.status==='ready'?'可用':'待配置'}</span></div></div>`).join('')||'<div class="empty">暂无训练资源</div>';
    document.getElementById('view').innerHTML=`<section class="hero-panel"><div class="hero-left"><div class="hero-k">畅联云算法训练 · v${V37_VERSION}</div><h2>从素材到可部署模型</h2><p>导入素材，完成标注与训练，再通过检测台验证模型效果。</p><div class="hero-actions"><button class="btn primary" onclick="setPage('数据集')">准备数据</button><button class="btn" onclick="setPage('训练任务')">创建训练</button><button class="btn" onclick="setPage('检测台')">检测模型</button></div></div></section>
      <section class="panel"><div class="panel-head"><div class="panel-title">快速入口</div></div><div class="panel-body"><div class="quick-grid-v37"><div class="quick-card-v37" onclick="setPage('数据集')"><div class="quick-icon-v37">${icon('数据集')}</div><b>导入与标注</b><span>图片、标注包、本机路径或服务器地址</span></div><div class="quick-card-v37" onclick="setPage('自动标注')"><div class="quick-icon-v37">${icon('自动标注')}</div><b>模型自动标注</b><span>选择模型配置与提示词模板</span></div><div class="quick-card-v37" onclick="setPage('训练任务')"><div class="quick-icon-v37">${icon('训练任务')}</div><b>创建训练任务</b><span>Ultralytics 或 PaddleDetection</span></div><div class="quick-card-v37" onclick="setPage('测试发布')"><div class="quick-icon-v37">${icon('测试发布')}</div><b>测试与导出</b><span>验证、发布和部署目标导出</span></div></div></div></section>
      <div class="dashboard-grid-v37"><section class="panel"><div class="panel-head"><div class="panel-title">最近训练</div><button class="btn small" onclick="setPage('训练任务')">全部任务</button></div><div class="panel-body"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>数据集</th><th>操作</th></tr></thead><tbody>${taskRows}</tbody></table></div></section><section class="panel"><div class="panel-head"><div class="panel-title">训练资源</div><button class="btn small" onclick="setPage('训练资源')">配置</button></div><div class="panel-body">${resourceRows}</div></section></div>`;
  };


  const modalEl=document.getElementById('modal');if(modalEl)modalEl.addEventListener('mousedown',e=>{if(e.target===modalEl)closeModal()});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!document.getElementById('modal')?.classList.contains('hidden'))closeModal()});

})();

// ============================================================
// v39: 部署转换中心 - 真实 ONNX / TensorRT / BMODEL / OM 工具链
// ============================================================
(function(){
  const V39='42.24.0';
  state.deployResources=[];state.deploySources=[];state.deployJobs=[];state.deployArtifacts=[];
  state.deployTarget=state.deployTarget||'onnx';state.deployLoaded=false;state.deployPresetSourceId='';
  const TARGETS={
    onnx:{name:'通用 ONNX',sub:'跨框架中间模型',ext:'.onnx',icon:'ONNX'},
    paddle_inference:{name:'Paddle Inference',sub:'飞桨部署模型',ext:'.pdmodel / .pdiparams',icon:'P'},
    tensorrt:{name:'NVIDIA TensorRT',sub:'GPU 优化 Engine',ext:'.engine',icon:'TRT'},
    sophon:{name:'算能 Sophon',sub:'TPU-MLIR 编译',ext:'.bmodel',icon:'BM'},
    ascend:{name:'华为 Atlas / Ascend',sub:'CANN ATC 编译',ext:'.om',icon:'OM'},
    rockchip:{name:'瑞芯微 RKNN',sub:'RKNN-Toolkit2 编译',ext:'.rknn',icon:'RK'},
  };
  const MENUS=[
    {title:'资产中心',items:['工作台','算法列表']},
    {title:'数据中心',items:['数据集','视频切帧','自动标注']},
    {title:'训练中心',items:['训练任务','测试发布','检测台']},
    {title:'部署中心',items:['部署转换','部署产物']},
    {title:'配置中心',items:['模型配置','训练资源','部署资源','部署插件','组件检测']},
  ];
  const META={
    '工作台':['首页','数据、训练、部署统一管理'],'算法列表':['资产中心','算法版本与训练资产'],'数据集':['数据中心','素材、标注与数据划分'],'视频切帧':['数据中心','视频自动抽帧'],'自动标注':['数据中心','模型辅助生成标注'],'训练任务':['训练中心','创建并跟踪训练任务'],'测试发布':['训练中心','模型测试与版本发布'],'检测台':['训练中心','原始模型与训练模型对比'],'部署转换':['部署中心','把源模型编译成目标硬件可运行模型'],'部署产物':['部署中心','管理 ONNX、RKNN、Engine、BMODEL、OM 等产物'],'模型配置':['配置中心','本地与云端模型配置'],'训练资源':['配置中心','训练框架与服务器'],'部署资源':['配置中心','芯片编译器与远程转换服务器'],'部署插件':['配置中心','厂商转换插件与 SDK 状态'],'组件检测':['配置中心','检查训练、导出与芯片部署组件']
  };
  const MENU_ICONS={
    '工作台':'<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>',
    '算法列表':'<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1.3"/><circle cx="4" cy="12" r="1.3"/><circle cx="4" cy="18" r="1.3"/>',
    '数据集':'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    '视频切帧':'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3z"/>',
    '自动标注':'<path d="m12 3 1.4 4.1 4.1 1.4-4.1 1.4L12 14l-1.4-4.1-4.1-1.4 4.1-1.4z"/>',
    '训练任务':'<path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/>',
    '测试发布':'<path d="M12 3v12M7 8l5-5 5 5M5 15v5h14v-5"/>',
    '检测台':'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',
    '部署转换':'<path d="M4 7h10M11 4l3 3-3 3M20 17H10M13 14l-3 3 3 3"/><rect x="3" y="13" width="4" height="8" rx="1"/><rect x="17" y="3" width="4" height="8" rx="1"/>',
    '部署产物':'<path d="M4 7 12 3l8 4-8 4zM4 7v10l8 4 8-4V7M12 11v10"/>',
    '模型配置':'<path d="M4 5h16v14H4zM8 9h8M8 13h5"/>',
    '训练资源':'<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
    '部署资源':'<rect x="4" y="4" width="16" height="6" rx="2"/><rect x="4" y="14" width="16" height="6" rx="2"/><path d="M8 7h.01M8 17h.01M12 7h5M12 17h5"/>','部署插件':'<path d="M8 3v4M16 3v4M6 7h12v5a6 6 0 0 1-12 0zM12 18v3"/>','组件检测':'<path d="M4 12h3l2-5 4 10 2-5h5"/><circle cx="12" cy="12" r="9"/>'
  };
  function menuIcon(n){return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${MENU_ICONS[n]||'<circle cx="12" cy="12" r="8"/>'}</svg>`}
  function targetName(k){return TARGETS[k]?.name||k}
  function targetBadge(k){return `<span class="deploy-target-badge">${esc(TARGETS[k]?.icon||k)}</span>`}
  function statusPill(s){return `<span class="pill ${s==='ready'||s==='done'?'ok':s==='failed'||s==='missing'?'err':'warn'}">${esc(({ready:'可用',missing:'不可用',unchecked:'未检测',queued:'排队中',running:'转换中',done:'已完成',failed:'失败',stopped:'已停止'}[s]||s||'-'))}</span>`}

  // Replace final v37 navigation while keeping the existing pages unchanged.
  renderNav=function(){
    const projectName=esc(state.project?.name||'默认空间');
    document.getElementById('nav').innerHTML=`<div class="nav-project"><div class="nav-project-k">当前项目</div><div class="nav-project-v" title="${projectName}">${projectName}</div></div>${MENUS.map(g=>`<div class="nav-group"><div class="nav-group-title">${g.title}</div>${g.items.map(n=>`<button class="nav-btn ${state.page===n?'active':''}" title="${n}" onclick="setPage('${n}')"><span class="nav-left"><i>${menuIcon(n)}</i><b>${n}</b></span><span class="nav-arrow">›</span></button>`).join('')}</div>`).join('')}<div class="nav-footer"><span>版本</span><b>v${V39}</b></div>`;
  };
  renderTop=function(){
    const meta=META[state.page]||['畅联云算法训练',''];
    const c=document.getElementById('crumb'),t=document.getElementById('title'),d=document.getElementById('pageDesc');
    if(c)c.textContent=meta[0];if(t)t.textContent=state.page;if(d)d.textContent=meta[1];
    const p=document.querySelector('#projectBadge span:last-child');if(p)p.textContent=state.project?.name||'默认空间';
    const v=document.getElementById('versionBadge');if(v)v.textContent='v'+V39;
    const r=document.getElementById('refreshBtn');if(r){r.textContent='刷新';r.onclick=async()=>{r.disabled=true;try{if(['部署转换','部署产物','部署资源'].includes(state.page)){await loadDeployData(true);render()}else{const page=state.page;await loadAll();state.page=page;render()}toast('已刷新')}finally{r.disabled=false}}}
  };

  async function loadDeployData(force=false){
    if(!pid())return;
    const cacheKey=`cl_algo_deploy_cache_${pid()}`;
    const ttl=10*60*1000;
    if(!force){
      try{
        const cached=JSON.parse(localStorage.getItem(cacheKey)||'null');
        if(cached){
          state.deployResources=cached.resources||[];state.deploySources=cached.sources||[];state.deployJobs=cached.jobs||[];state.deployArtifacts=cached.artifacts||[];state.deployLoaded=true;return;
        }
      }catch(e){}
    }
    const [rr,ss,jj,aa]=await Promise.all([
      safe(api('/api/v39/deploy/resources')),
      safe(api(`/api/v39/projects/${pid()}/deploy/source-models`)),
      safe(api(`/api/v39/projects/${pid()}/deploy/jobs`)),
      safe(api(`/api/v39/projects/${pid()}/deploy/artifacts`)),
    ]);
    state.deployResources=rr?.items||[];state.deploySources=ss?.items||[];state.deployJobs=jj?.items||[];state.deployArtifacts=aa?.items||[];state.deployLoaded=true;
    try{localStorage.setItem(cacheKey,JSON.stringify({ts:Date.now(),resources:state.deployResources,sources:state.deploySources,jobs:state.deployJobs,artifacts:state.deployArtifacts}))}catch(e){}
  }
  window.loadDeployData=loadDeployData;

  function deployResourceCard(r){
    const targetHtml=(r.targets||[]).map(x=>`<span class="chip-tag">${esc(targetName(x))}</span>`).join('')||'<span class="muted-line">暂无可用转换能力</span>';
    const built=!!r.builtin;
    return `<div class="deploy-resource-card ${r.status==='ready'?'is-ready':''}"><div class="deploy-res-head"><div class="deploy-res-logo">${r.kind==='sophon'?'BM':r.kind==='ascend'?'A':r.kind==='rockchip'?'RK':r.kind==='tensorrt'?'N':r.kind==='paddle'?'P':'U'}</div><div class="grow"><div class="item-title">${esc(r.name)}</div><div class="item-sub">${esc(r.mode==='remote'?'远程服务器':'本机')} · ${esc(r.version||'')}</div></div>${statusPill(r.status)}</div><div class="deploy-capabilities">${targetHtml}</div><div class="item-sub deploy-message">${esc(r.message||'')}</div><div class="row end">${!built?`<button class="btn mini" onclick="editDeployResource('${r.id}')">编辑</button>`:''}<button class="btn mini primary" onclick="detectDeployResource('${r.id}')">检测</button>${!built?`<button class="btn mini danger" onclick="deleteDeployResource('${r.id}')">删除</button>`:''}</div></div>`;
  }
  window.renderDeployResources=function(){
    if(!state.deployLoaded){document.getElementById('view').innerHTML='<div class="loading">正在读取部署资源...</div>';loadDeployData().then(renderDeployResources);return}
    document.getElementById('view').innerHTML=`<section class="panel"><div class="panel-head"><div><div class="panel-title">部署资源</div><div class="subline">只把真实检测通过的编译器标记为可用</div></div><div class="panel-actions"><button class="btn" onclick="autoDetectDeployResources()">检测本机工具</button><button class="btn primary" onclick="openDeployResourceModal()">新增部署资源</button></div></div><div class="panel-body"><div class="deploy-resource-grid">${(state.deployResources||[]).map(deployResourceCard).join('')||'<div class="empty">暂无部署资源</div>'}</div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">远程转换服务器</div></div><div class="panel-body"><div class="compact-note">瑞芯微 RKNN-Toolkit2、算能 TPU-MLIR、华为 CANN/ATC 都按厂商真实工具链执行。Windows 主机可直接完成 ONNX；RKNN/算能/昇腾建议配置 Linux/WSL2/转换服务器。把 <b>remote_deploy_server.py</b> 放到对应 Linux 转换节点启动后，在这里新增“远程”资源，平台会自动上传模型、执行转换并拉回产物。</div></div></section>`;
  };
  window.autoDetectDeployResources=async()=>{const b=document.querySelector('[onclick="autoDetectDeployResources()"]');if(b){b.disabled=true;b.innerHTML='<span class="tiny-spinner"></span>检测中'}try{const r=await api('/api/v39/deploy/local/auto-detect',{method:'POST'});state.deployResources=r.items||[];renderDeployResources();toast(r.found?.length?`检测到 ${r.found.length} 个本机部署工具`:'未检测到额外的芯片编译器')}catch(e){toast(e.message||e)}finally{if(b){b.disabled=false;b.textContent='检测本机工具'}}};
  window.detectDeployResource=async id=>{const card=[...document.querySelectorAll('.deploy-resource-card')].find(x=>x.innerText.includes((state.deployResources.find(r=>r.id===id)||{}).name||''));try{const r=await api(`/api/v39/deploy/resources/${id}/detect`,{method:'POST'});const i=state.deployResources.findIndex(x=>x.id===id);if(i>=0)state.deployResources[i]=r;renderDeployResources();toast(r.status==='ready'?'部署资源可用':r.message||'检测未通过')}catch(e){toast(e.message||e)}};
  function deployResourceForm(r={}){
    return `<div class="form"><div class="grid2-mini"><div class="field"><label>资源名称</label><input id="drName" class="input" value="${esc(r.name||'')}"></div><div class="field"><label>运行位置</label><select id="drMode" class="select" onchange="toggleDeployResourceFields()"><option value="local" ${r.mode!=='remote'?'selected':''}>本机</option><option value="remote" ${r.mode==='remote'?'selected':''}>远程转换服务器</option></select></div></div><div class="field"><label>资源类型</label><select id="drKind" class="select" onchange="toggleDeployResourceFields()"><option value="sophon" ${r.kind==='sophon'?'selected':''}>算能 TPU-MLIR</option><option value="ascend" ${r.kind==='ascend'?'selected':''}>华为 CANN / ATC</option><option value="rockchip" ${r.kind==='rockchip'?'selected':''}>瑞芯微 RKNN-Toolkit2</option><option value="tensorrt" ${r.kind==='tensorrt'?'selected':''}>NVIDIA TensorRT</option><option value="ultralytics" ${r.kind==='ultralytics'?'selected':''}>Ultralytics 导出</option><option value="paddle" ${r.kind==='paddle'?'selected':''}>PaddleDetection 导出</option></select></div><div id="drRemote"><div class="field"><label>服务地址</label><input id="drUrl" class="input" value="${esc(r.base_url||'')}" placeholder="http://192.168.10.20:8030"></div><div class="field"><label>API Key</label><input id="drKey" class="input" value="${esc(r.api_key||'')}"></div></div><div id="drLocal"><div class="field"><label>工具目录</label><input id="drRoot" class="input" value="${esc(r.tool_root||'')}" placeholder="例如 /workspace/tpu-mlir 或 /usr/local/Ascend/ascend-toolkit/latest"></div><div class="field"><label>Python 路径</label><input id="drPython" class="input" value="${esc(r.python_path||'')}" placeholder="留空使用平台 Python"></div><div id="drPaddle"><div class="field"><label>PaddleDetection 目录</label><input id="drPaddleDir" class="input" value="${esc(r.paddledet_dir||'')}"></div><div class="field"><label>paddle2onnx</label><input id="drP2O" class="input" value="${esc(r.paddle2onnx_path||'')}"></div></div><div id="drTrt"><div class="field"><label>trtexec 路径</label><input id="drTrtPath" class="input" value="${esc(r.trtexec_path||'')}"></div></div><div id="drAscend"><div class="field"><label>ATC 路径</label><input id="drAtcPath" class="input" value="${esc(r.atc_path||'')}"></div><div class="field"><label>CANN 环境脚本</label><input id="drEnv" class="input" value="${esc(r.env_script||'')}" placeholder="/usr/local/Ascend/ascend-toolkit/set_env.sh"></div></div></div><div class="field"><label>备注</label><input id="drRemark" class="input" value="${esc(r.remark||'')}"></div><button class="btn primary" onclick="saveDeployResource('${esc(r.id||'')}')">保存并返回</button></div>`;
  }
  window.openDeployResourceModal=()=>{modal('新增部署资源',deployResourceForm(),true);toggleDeployResourceFields()};
  window.editDeployResource=id=>{const r=state.deployResources.find(x=>x.id===id);modal('编辑部署资源',deployResourceForm(r||{}),true);toggleDeployResourceFields()};
  window.toggleDeployResourceFields=()=>{const mode=document.getElementById('drMode')?.value||'local',kind=document.getElementById('drKind')?.value||'';document.getElementById('drRemote')?.classList.toggle('hidden',mode!=='remote');document.getElementById('drLocal')?.classList.toggle('hidden',mode==='remote');document.getElementById('drPaddle')?.classList.toggle('hidden',kind!=='paddle');document.getElementById('drTrt')?.classList.toggle('hidden',kind!=='tensorrt');document.getElementById('drAscend')?.classList.toggle('hidden',kind!=='ascend')};
  window.saveDeployResource=async id=>{const body={name:document.getElementById('drName')?.value||'',kind:document.getElementById('drKind')?.value||'sophon',mode:document.getElementById('drMode')?.value||'local',base_url:document.getElementById('drUrl')?.value||'',api_key:document.getElementById('drKey')?.value||'',python_path:document.getElementById('drPython')?.value||'',tool_root:document.getElementById('drRoot')?.value||'',paddledet_dir:document.getElementById('drPaddleDir')?.value||'',paddle2onnx_path:document.getElementById('drP2O')?.value||'',trtexec_path:document.getElementById('drTrtPath')?.value||'',atc_path:document.getElementById('drAtcPath')?.value||'',env_script:document.getElementById('drEnv')?.value||'',remark:document.getElementById('drRemark')?.value||''};if(!body.name.trim())return toast('请输入资源名称');try{await api(id?`/api/v39/deploy/resources/${id}`:'/api/v39/deploy/resources',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeModal();await loadDeployData(true);renderDeployResources();toast('已保存，请执行检测')}catch(e){toast(e.message||e)}};
  window.deleteDeployResource=async id=>{if(!confirm('确认删除这个部署资源？'))return;await safe(api(`/api/v39/deploy/resources/${id}`,{method:'DELETE'}));await loadDeployData(true);renderDeployResources()};

  function sourceOptions(){return (state.deploySources||[]).map(s=>`<option value="${esc(s.id)}" ${state.deployPresetSourceId===s.id?'selected':''}>${esc(s.label||s.name)} · .${esc(s.type||'')}</option>`).join('')}
  function compatibleResources(target){return (state.deployResources||[]).filter(r=>r.status==='ready'&&(r.targets||[]).includes(target))}
  function targetCards(){return Object.entries(TARGETS).map(([k,t])=>{const n=compatibleResources(k).length;return `<button type="button" class="deploy-target-card ${state.deployTarget===k?'active':''}" onclick="selectDeployTarget('${k}')"><span class="deploy-target-icon">${t.icon}</span><span class="grow"><b>${t.name}</b><small>${t.sub}</small></span><em>${n?`${n} 个资源`:'未配置'}</em></button>`}).join('')}
  window.selectDeployTarget=k=>{state.deployTarget=k;renderDeployFormOnly()};
  function configFields(target){
    if(target==='onnx')return `<div class="deploy-config-grid"><div class="field"><label>输入尺寸</label><input id="dpInput" class="input" value="640"></div><div class="field"><label>ONNX Opset</label><input id="dpOpset" class="input" value="12"></div><div class="field check"><label><input id="dpDynamic" type="checkbox"> 动态 Shape</label></div><div class="field check"><label><input id="dpSimplify" type="checkbox"> Simplify</label></div></div>`;
    if(target==='paddle_inference')return `<div class="compact-note">平台会调用 PaddleDetection <b>tools/export_model.py</b>，使用训练时 yml 和 .pdparams 生成真实推理模型。</div>`;
    if(target==='tensorrt')return `<div class="deploy-config-grid"><div class="field"><label>输入尺寸</label><input id="dpInput" class="input" value="640"></div><div class="field"><label>精度</label><select id="dpPrecision" class="select"><option value="fp16">FP16</option><option value="fp32">FP32</option></select></div><div class="field"><label>Workspace(MB)</label><input id="dpWorkspace" class="input" value="2048"></div><div class="field"><label>Batch</label><input id="dpBatch" class="input" value="1"></div></div>`;
    if(target==='rockchip')return `<div class="deploy-config-grid"><div class="field"><label>目标芯片</label><select id="dpChip" class="select"><option value="rk3588">RK3588</option><option value="rk3576">RK3576</option><option value="rk3568">RK3568</option><option value="rk3566">RK3566</option><option value="rk3562">RK3562</option><option value="rv1103b">RV1103B</option><option value="rv1106b">RV1106B</option><option value="rv1126b">RV1126B</option></select></div><div class="field"><label>精度</label><select id="dpPrecision" class="select" onchange="toggleRockchipCalibration()"><option value="fp16">浮点模型</option><option value="int8">INT8</option></select></div><div class="field"><label>输入尺寸</label><input id="dpInput" class="input" value="640"></div><div class="field"><label>Batch</label><input id="dpBatch" class="input" value="1"></div></div><div id="rockchipCali" class="sophon-cali hidden"><div class="divider"></div><div class="deploy-config-grid"><div class="field"><label>校准数据集</label><select id="dpDataset" class="select">${(state.datasets||[]).map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div><div class="field"><label>数据分组</label><select id="dpCaliSplit" class="select"><option value="train">训练集</option><option value="val">试验集</option><option value="test">评测集</option><option value="all">全部</option></select></div><div class="field"><label>校准图片数</label><input id="dpCaliCount" class="input" value="100"></div></div></div>`;
    if(target==='sophon')return `<div class="deploy-config-grid"><div class="field"><label>目标芯片</label><select id="dpChip" class="select"><option value="bm1684x">BM1684X</option><option value="bm1688">BM1688</option><option value="bm1690">BM1690</option><option value="cv186x">CV186X</option></select></div><div class="field"><label>精度</label><select id="dpPrecision" class="select" onchange="toggleSophonCalibration()"><option value="fp16">FP16</option><option value="bf16">BF16</option><option value="fp32">FP32</option><option value="int8">INT8</option></select></div><div class="field"><label>输入尺寸</label><input id="dpInput" class="input" value="640"></div><div class="field"><label>Batch</label><input id="dpBatch" class="input" value="1"></div><div class="field"><label>像素格式</label><select id="dpPixel" class="select"><option value="rgb">RGB</option><option value="bgr">BGR</option></select></div><div class="field"><label>Scale</label><input id="dpScale" class="input" value="0.0039216,0.0039216,0.0039216"></div><div class="field"><label>Mean</label><input id="dpMean" class="input" value="0,0,0"></div><div class="field"><label>TPU Core</label><input id="dpCore" class="input" value="1"></div></div><div id="sophonCali" class="sophon-cali hidden"><div class="divider"></div><div class="deploy-config-grid"><div class="field"><label>校准数据集</label><select id="dpDataset" class="select">${(state.datasets||[]).map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div><div class="field"><label>数据分组</label><select id="dpCaliSplit" class="select"><option value="train">训练集</option><option value="val">试验集</option><option value="test">评测集</option><option value="all">全部</option></select></div><div class="field"><label>校准图片数</label><input id="dpCaliCount" class="input" value="100"></div><div class="field"><label>校准方法</label><select id="dpCaliMethod" class="select"><option value="">KLD（默认）</option><option value="mse">MSE</option><option value="max">MAX</option><option value="percentile9999">Percentile9999</option></select></div></div></div>`;
    if(target==='ascend')return `<div class="deploy-config-grid"><div class="field"><label>Atlas 设备</label><select id="dpAtlasProduct" class="select"><option value="Atlas 300I Pro">Atlas 300I Pro</option><option value="Atlas 300V">Atlas 300V</option><option value="Atlas 300V Pro">Atlas 300V Pro</option><option value="Atlas 300I Duo">Atlas 300I Duo</option><option value="Atlas 200I SoC A1">Atlas 200I SoC A1</option><option value="Atlas A2 / 其他">Atlas A2 / 其他</option></select></div><div class="field"><label>SoC Version</label><input id="dpSoc" class="input" list="socList" value="Ascend310P3"><datalist id="socList"><option value="Ascend310P3"><option value="Ascend310P1"><option value="Ascend310B"><option value="Ascend310B4"><option value="Ascend910B"></datalist></div><div class="field"><label>输入尺寸</label><input id="dpInput" class="input" value="640"></div><div class="field"><label>输入节点名</label><input id="dpInputName" class="input" value="images"></div><div class="field"><label>Batch</label><input id="dpBatch" class="input" value="1"></div><div class="field"><label>精度模式</label><select id="dpPrecisionMode" class="select"><option value="allow_fp32_to_fp16">允许 FP32→FP16</option><option value="must_keep_origin_dtype">保持原精度</option><option value="allow_mix_precision">混合精度</option></select></div><div class="field check"><label><input id="dpAipp" type="checkbox" onchange="toggleAippConfig()"> 启用 AIPP 预处理</label></div></div><div id="aippBox" class="hidden"><div class="field"><label>AIPP 配置</label><textarea id="dpAippConfig" placeholder="留空时按 RGB888_U8 + 1/255 生成基础配置"></textarea></div></div>`;
    return '';
  }
  window.toggleSophonCalibration=()=>document.getElementById('sophonCali')?.classList.toggle('hidden',(document.getElementById('dpPrecision')?.value||'')!=='int8');
  window.toggleRockchipCalibration=()=>document.getElementById('rockchipCali')?.classList.toggle('hidden',(document.getElementById('dpPrecision')?.value||'')!=='int8');
  window.toggleAippConfig=()=>document.getElementById('aippBox')?.classList.toggle('hidden',!document.getElementById('dpAipp')?.checked);
  function renderDeployFormOnly(){
    const box=document.getElementById('deployCreateBox');if(!box)return;
    const resources=compatibleResources(state.deployTarget);const sourceSel=sourceOptions();
    const configured=(state.deployResources||[]).filter(r=>String(r.kind||'').toLowerCase()===String(state.deployTarget||'').toLowerCase()||(r.targets||[]).includes(state.deployTarget));
    const resourceStatus=configured.length?configured.map(r=>{const ready=resources.some(x=>x.id===r.id),detail=r.message||(!ready?'请执行检测并确认该目标能力':'可以创建真实转换任务');return `<div class="deploy-resource-readiness-row ${ready?'ready':'not-ready'}"><div><b>${esc(r.name||r.id||'未命名资源')}</b><span>${esc(r.mode==='remote'?'远程服务器':'本机')}</span>${statusPill(r.status)}</div><p>${esc(detail)}</p></div>`}).join(''):`<div class="deploy-resource-readiness-empty"><b>尚未配置 ${esc(targetName(state.deployTarget))} 转换资源</b><span>请新增本机工具链或远程转换服务器，再执行检测。</span></div>`;
    box.innerHTML=`<div class="deploy-create-grid"><div><div class="field"><label>源模型</label><select id="dpSource" class="select">${sourceSel||'<option value="">暂无已训练模型</option>'}</select></div><div class="field"><label>部署目标</label><div class="deploy-targets">${targetCards()}</div></div></div><div class="deploy-config-panel"><div class="field"><label>执行资源</label><select id="dpResource" class="select" onchange="syncAtlasSocFromResource()">${resources.map(r=>`<option value="${r.id}">${esc(r.name)} · ${r.mode==='remote'?'远程':'本机'}</option>`).join('')||'<option value="">当前目标没有已检测可用资源</option>'}</select></div><section class="deploy-resource-readiness"><header><b>当前目标的转换资源</b><span>只有状态为“可用”的资源才允许创建真实转换任务。</span></header>${resourceStatus}<button class="btn mini" type="button" onclick="setPage('部署资源')">配置 / 检测资源</button></section>${configFields(state.deployTarget)}<button class="btn primary deploy-submit" ${resources.length&&state.deploySources.length?'':'disabled'} onclick="createDeployJob()">创建转换任务</button></div></div>`;
    if(state.deployTarget==='sophon')toggleSophonCalibration();if(state.deployTarget==='rockchip')toggleRockchipCalibration();if(state.deployTarget==='ascend')setTimeout(syncAtlasSocFromResource,0);
  }
  function jobRow(j){const params=j.params||{};const chip=params.chip||params.soc_version||'';const isRun=['queued','running'].includes(j.status);return `<div class="deploy-job"><div class="deploy-job-main"><div class="deploy-job-icon">${TARGETS[j.target]?.icon||'→'}</div><div class="grow"><div class="item-title">${esc(j.source_name||'模型')} → ${esc(targetName(j.target))}${chip?' / '+esc(chip):''}</div><div class="item-sub">${esc(j.resource?.name||'-')} · ${esc(j.stage||'')}</div></div>${statusPill(j.status)}</div><div class="deploy-progress"><div class="progress-bar"><i style="width:${Math.max(0,Math.min(100,j.progress||0))}%"></i></div><span>${Math.round(j.progress||0)}%</span></div>${j.error?`<div class="alert err">${esc(j.error)}</div>`:''}<div class="row end"><button class="btn mini" onclick="openDeployLog('${j.id}')">日志</button>${isRun?`<button class="btn mini danger" onclick="stopDeployJob('${j.id}')">停止</button>`:''}${j.status==='done'?`<a class="btn mini primary" href="/api/v39/projects/${pid()}/deploy/jobs/${j.id}/package">下载部署包</a>`:''}${!isRun?`<button class="btn mini danger" onclick="deleteDeployJob('${j.id}')">删除</button>`:''}</div></div>`}
  function renderDeployJobsOnly(){const box=document.getElementById('deployJobList');if(!box)return;box.innerHTML=(state.deployJobs||[]).map(jobRow).join('')||'<div class="empty">暂无转换任务</div>'}
  async function pollDeployJobs(){if(state.page!=='部署转换')return;const r=await safe(api(`/api/v39/projects/${pid()}/deploy/jobs`));if(r){state.deployJobs=r.items||[];renderDeployJobsOnly()}if((state.deployJobs||[]).some(j=>['queued','running'].includes(j.status))){clearTimeout(window.__deployPollV39);window.__deployPollV39=setTimeout(pollDeployJobs,1800)}}
  window.renderDeployCenter=function(){
    if(!state.deployLoaded){document.getElementById('view').innerHTML='<div class="loading">正在读取模型与部署资源...</div>';loadDeployData().then(renderDeployCenter);return}
    document.getElementById('view').innerHTML=`<section class="panel"><div class="panel-head"><div><div class="panel-title">创建部署转换</div><div class="subline">训练模型和部署模型分离；任务会调用真实厂商工具链</div></div><button class="btn small" onclick="setPage('部署资源')">配置部署资源</button></div><div class="panel-body" id="deployCreateBox"></div></section><section class="panel"><div class="panel-head"><div class="panel-title">转换任务</div><button class="btn small" onclick="loadDeployData(true).then(()=>{renderDeployJobsOnly()})">刷新</button></div><div class="panel-body"><div id="deployJobList" class="deploy-job-list"></div></div></section>`;
    renderDeployFormOnly();renderDeployJobsOnly();pollDeployJobs();
  };
  window.syncAtlasSocFromResource=()=>{if(state.deployTarget!=='ascend')return;const rid=document.getElementById('dpResource')?.value;const r=(state.deployResources||[]).find(x=>x.id===rid);const soc=document.getElementById('dpSoc');if(!soc||!r)return;const vals=r.detected_soc_versions||r.remote_health?.tools?.soc_versions||[];if(vals.length)soc.value=vals[0];};
  window.createDeployJob=async()=>{const source=document.getElementById('dpSource')?.value||'',resource=document.getElementById('dpResource')?.value||'';if(!source)return toast('请选择源模型');if(!resource)return toast('当前目标没有可用部署资源');const t=state.deployTarget;const size=parseInt(document.getElementById('dpInput')?.value||'640');const params={input_size:size,input_width:size,input_height:size,batch:parseInt(document.getElementById('dpBatch')?.value||'1'),opset:parseInt(document.getElementById('dpOpset')?.value||'12'),dynamic:!!document.getElementById('dpDynamic')?.checked,simplify:!!document.getElementById('dpSimplify')?.checked,precision:document.getElementById('dpPrecision')?.value||'fp16',workspace_mb:parseInt(document.getElementById('dpWorkspace')?.value||'2048'),chip:document.getElementById('dpChip')?.value||'',pixel_format:document.getElementById('dpPixel')?.value||'rgb',scale:document.getElementById('dpScale')?.value||'0.0039216,0.0039216,0.0039216',mean:document.getElementById('dpMean')?.value||'0,0,0',num_core:parseInt(document.getElementById('dpCore')?.value||'1'),calibration_method:document.getElementById('dpCaliMethod')?.value||'',soc_version:document.getElementById('dpSoc')?.value||'',atlas_product:document.getElementById('dpAtlasProduct')?.value||'',input_name:document.getElementById('dpInputName')?.value||'images',precision_mode:document.getElementById('dpPrecisionMode')?.value||'',aipp_enabled:!!document.getElementById('dpAipp')?.checked,aipp_config:document.getElementById('dpAippConfig')?.value||''};const body={source_id:source,target:t,resource_id:resource,params,dataset_id:document.getElementById('dpDataset')?.value||state.datasetId||'default',calibration_split:document.getElementById('dpCaliSplit')?.value||'train',calibration_count:parseInt(document.getElementById('dpCaliCount')?.value||'100')};const btn=document.querySelector('.deploy-submit');if(btn){btn.disabled=true;btn.innerHTML='<span class="tiny-spinner"></span>创建中'}try{await api(`/api/v39/projects/${pid()}/deploy/jobs`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});state.deployPresetSourceId='';await loadDeployData(true);renderDeployCenter();toast('转换任务已创建')}catch(e){toast(e.message||e)}finally{if(btn){btn.disabled=false;btn.textContent='创建转换任务'}}};
  window.stopDeployJob=async id=>{await safe(api(`/api/v39/projects/${pid()}/deploy/jobs/${id}/stop`,{method:'POST'}));await pollDeployJobs()};
  window.deleteDeployJob=async id=>{if(!confirm('确认删除这条转换任务和产物？'))return;await safe(api(`/api/v39/projects/${pid()}/deploy/jobs/${id}`,{method:'DELETE'}));await loadDeployData(true);renderDeployJobsOnly()};
  window.openDeployLog=async id=>{const job=(state.deployJobs||[]).find(x=>x.id===id)||{};const txt=await safe(api(`/api/v39/projects/${pid()}/deploy/jobs/${id}/log`))||'';modal(`转换日志 · ${job.source_name||id}`,`<div class="deploy-log-head"><div>${statusPill(job.status)} <span class="item-sub">${esc(job.stage||'')}</span></div><button class="btn mini" onclick="refreshDeployLog('${id}')">刷新</button></div><pre id="deployLogText" class="log deploy-log">${esc(txt)}</pre>`,true);const pre=document.getElementById('deployLogText');if(pre)pre.scrollTop=pre.scrollHeight};
  window.refreshDeployLog=async id=>{const txt=await safe(api(`/api/v39/projects/${pid()}/deploy/jobs/${id}/log`))||'';const p=document.getElementById('deployLogText');if(p){p.textContent=txt;p.scrollTop=p.scrollHeight}};

  window.renderDeployArtifacts=function(){
    if(!state.deployLoaded){document.getElementById('view').innerHTML='<div class="loading">正在读取部署产物...</div>';loadDeployData().then(renderDeployArtifacts);return}
    const rows=(state.deployArtifacts||[]).map(a=>`<tr><td>${targetBadge(a.target)} <b>${esc(a.name)}</b><div class="muted-line">${esc(a.source_name||'')}</div></td><td>${esc(targetName(a.target))}</td><td>${esc(a.params?.chip||a.params?.soc_version||'-')}</td><td>${esc((a.params?.precision||'-').toUpperCase())}</td><td>${a.size_mb||0} MB</td><td>${esc(a.created_at||'')}</td><td><a class="btn mini primary" href="${esc(a.download_url)}">下载</a><button class="btn mini" onclick="openDeployLog('${a.job_id}')">日志</button></td></tr>`).join('')||'<tr><td colspan="7">暂无部署产物</td></tr>';
    document.getElementById('view').innerHTML=`<section class="panel"><div class="panel-head"><div><div class="panel-title">部署产物</div><div class="subline">每个文件都来自真实转换任务，可追溯源模型、芯片和参数</div></div><button class="btn primary small" onclick="setPage('部署转换')">创建转换</button></div><div class="panel-body"><table class="table"><thead><tr><th>产物</th><th>目标</th><th>芯片</th><th>精度</th><th>大小</th><th>时间</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
  };

  // Add deployment action to algorithm version management.
  window.startDeployVersion=(aid,vid)=>{state.deployPresetSourceId=`version::${aid}::${vid}`;closeModal();state.deployLoaded=false;return window.setPage?.('部署转换')};
  // Add deployment to dashboard without adding explanatory clutter.
  window.renderHomeDashboard=function(){
    const recent=(state.jobs||[]).slice(0,5),running=(state.jobs||[]).filter(j=>['running','queued'].includes(j.status)).length,done=(state.jobs||[]).filter(j=>['done','finished','completed'].includes(j.status)).length;
    const taskRows=recent.map(j=>`<tr><td><b>${esc(j.algorithm_name||j.name||j.id)}</b></td><td>${statusPill(['done','finished','completed'].includes(j.status)?'done':j.status)}</td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td><button class="btn mini" onclick="setPage('训练任务')">查看</button></td></tr>`).join('')||'<tr><td colspan="4">暂无训练任务</td></tr>';
    document.getElementById('view').innerHTML=`<section class="hero-panel"><div class="hero-left"><div class="hero-k">畅联云算法训练 · v${V39}</div><h2>从素材到目标芯片部署</h2><p>数据准备、训练、检测、芯片转换和部署产物统一管理。</p><div class="hero-actions"><button class="btn primary" onclick="setPage('数据集')">准备数据</button><button class="btn" onclick="setPage('训练任务')">训练模型</button><button class="btn" onclick="setPage('部署转换')">部署转换</button></div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">快速入口</div></div><div class="panel-body"><div class="quick-grid-v39"><div class="quick-card-v37" onclick="setPage('数据集')"><div class="quick-icon-v37">${menuIcon('数据集')}</div><b>数据准备</b><span>导入、标注、划分</span></div><div class="quick-card-v37" onclick="setPage('自动标注')"><div class="quick-icon-v37">${menuIcon('自动标注')}</div><b>模型标注</b><span>提示词模板与自动标注</span></div><div class="quick-card-v37" onclick="setPage('训练任务')"><div class="quick-icon-v37">${menuIcon('训练任务')}</div><b>训练任务</b><span>Ultralytics / PaddleDetection</span></div><div class="quick-card-v37" onclick="setPage('检测台')"><div class="quick-icon-v37">${menuIcon('检测台')}</div><b>模型检测</b><span>同图对比效果</span></div><div class="quick-card-v37" onclick="setPage('部署转换')"><div class="quick-icon-v37">${menuIcon('部署转换')}</div><b>部署转换</b><span>ONNX / RKNN / BMODEL / OM / Engine</span></div></div></div></section><div class="dashboard-grid-v37"><section class="panel"><div class="panel-head"><div class="panel-title">最近训练</div><button class="btn small" onclick="setPage('训练任务')">全部</button></div><div class="panel-body"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>数据集</th><th></th></tr></thead><tbody>${taskRows}</tbody></table></div></section><section class="panel"><div class="panel-head"><div class="panel-title">当前进度</div></div><div class="panel-body"><div class="mini-metrics"><div><span>训练中</span><b>${running}</b></div><div><span>已完成</span><b>${done}</b></div><div><span>算法版本</span><b>${(state.algorithms||[]).reduce((n,a)=>n+(a.versions||[]).length,0)}</b></div></div></div></section></div>`;
  };

  const oldRenderV39=render;
  render=function(){
    state.versionInfo={...(state.versionInfo||{}),version:V39};
    if(state.page==='部署转换'){renderNav();renderTop();renderSummary();renderDeployCenter();return}
    if(state.page==='部署产物'){renderNav();renderTop();renderSummary();renderDeployArtifacts();return}
    if(state.page==='部署资源'){renderNav();renderTop();renderSummary();renderDeployResources();return}
    if(state.page==='部署插件'){renderNav();renderTop();renderSummary();renderDeployPluginsV41();return}
    if(state.page==='组件检测'){renderNav();renderTop();renderSummary();renderComponentCheckV40();return}
    oldRenderV39();
  };
  // existing setPage calls render dynamically; reset deployment cache on relevant pages only.
})();


// ============================================================
// v40: 组件检测中心
// ============================================================
(function(){
  state.componentScan=null;state.componentScanTimer=null;
  const compStatus=s=>`<span class="pill ${s==='ready'?'ok':s==='missing'?'err':'warn'}">${s==='ready'?'满足':s==='missing'?'缺失':'需确认'}</span>`;
  function compRow(c){return `<div class="component-row"><div class="component-state">${compStatus(c.status)}</div><div class="grow"><div class="item-title">${esc(c.name)}</div><div class="item-sub">${esc(c.version||'')}${c.path?` · ${esc(c.path)}`:''}</div>${c.detail?`<div class="component-detail">${esc(c.detail)}</div>`:''}${c.status!=='ready'&&c.fix?`<div class="component-fix">${esc(c.fix)}</div>`:''}</div></div>`}
  function capCard(c){return `<div class="capability-card ${c.status}"><div class="capability-head"><b>${esc(c.name)}</b>${compStatus(c.status)}</div><div class="item-sub">${c.remote?'远程部署资源可用':'本机/已配置资源'} · ${c.ready||0}/${c.total||0}</div></div>`}
  function renderCompBody(){const box=document.getElementById('componentBody');if(!box)return;const s=state.componentScan||{};const sum=s.summary||{ready:0,warning:0,missing:0,total:0};const running=['queued','running'].includes(s.status);box.innerHTML=`<div class="component-summary"><div><span>满足</span><b>${sum.ready||0}</b></div><div><span>需确认</span><b>${sum.warning||0}</b></div><div><span>缺失</span><b>${sum.missing||0}</b></div><div><span>总项</span><b>${sum.total||0}</b></div></div>${running?`<div class="component-progress"><div class="progress-bar"><i style="width:${s.progress||0}%"></i></div><div><b>${esc(s.stage||'检测中')}</b><span>${Math.round(s.progress||0)}%</span></div></div>`:''}<div class="capability-grid">${(s.capabilities||[]).map(capCard).join('')}</div><div class="component-grid"><section class="component-group"><div class="component-group-title">组件明细</div>${(s.components||[]).map(compRow).join('')||'<div class="empty">尚未检测</div>'}</section></div>${s.atlas?`<div class="atlas-check"><div><b>华为 Atlas / Ascend</b><span>${s.atlas.atc_ready?'OM 转换可用':'ATC 未就绪'}</span></div><div class="item-sub">${(s.atlas.detected_soc_versions||[]).length?'检测到 '+s.atlas.detected_soc_versions.join('、'):'未读取到本机 NPU；仍可在纯 CANN 转换服务器编译 OM，创建任务时填写目标 soc_version。'}</div></div>`:''}`}
  window.renderComponentCheckV40=async()=>{document.getElementById('view').innerHTML=`<section class="panel"><div class="panel-head"><div><div class="panel-title">组件检测</div><div class="subline">训练、导出、量化与芯片编译环境</div></div><button id="componentScanBtn" class="btn primary" onclick="startComponentScanV40()">开始检测</button></div><div class="panel-body" id="componentBody"><div class="loading">正在读取检测记录...</div></div></section>`;const latest=await safe(api('/api/v40/system/components/latest'));state.componentScan=latest||{};renderCompBody();if(['queued','running'].includes(state.componentScan?.status))pollComponentScanV40(state.componentScan.id)};
  window.startComponentScanV40=async()=>{const b=document.getElementById('componentScanBtn');if(b){b.disabled=true;b.innerHTML='<span class="tiny-spinner"></span>检测中'}try{const r=await api('/api/v40/system/components/scan',{method:'POST'});state.componentScan=r;renderCompBody();pollComponentScanV40(r.id)}catch(e){toast(e.message||e);if(b){b.disabled=false;b.textContent='开始检测'}}};
  window.pollComponentScanV40=async id=>{clearTimeout(state.componentScanTimer);const r=await safe(api(`/api/v40/system/components/scan/${id}`));if(r){state.componentScan=r;renderCompBody()}if(r&&['queued','running'].includes(r.status)){state.componentScanTimer=setTimeout(()=>pollComponentScanV40(id),650)}else{const b=document.getElementById('componentScanBtn');if(b){b.disabled=false;b.textContent='重新检测'}if(r?.status==='done')toast('组件检测完成')}};
})();

// ============================================================
// v41: 厂商部署插件中心
// ============================================================
(function(){
  state.deployPlugins=[];
  const pluginState=s=>`<span class="pill ${s==='ready'?'ok':'err'}">${s==='ready'?'可用':'缺少 SDK/工具链'}</span>`;
  window.loadDeployPluginsV41=async()=>{const r=await safe(api('/api/v41/deploy/plugins'));state.deployPlugins=r?.items||[];state.deployHostOs=r?.host_os||'';return state.deployPlugins};
  function pluginCard(p){
    const chips=(p.chips||[]).slice(0,7).map(x=>`<span class="chip-tag">${esc(x)}</span>`).join('');
    return `<div class="deploy-resource-card ${p.status==='ready'?'is-ready':''}"><div class="deploy-res-head"><div class="deploy-res-logo">${p.id==='rockchip'?'RK':p.id==='ascend'?'A':p.id==='sophon'?'BM':p.id==='tensorrt'?'N':'ON'}</div><div class="grow"><div class="item-title">${esc(p.name)}</div><div class="item-sub">${esc(p.sdk)} · 输出 ${esc(p.output)}</div></div>${pluginState(p.status)}</div><div class="deploy-capabilities">${chips||'<span class="muted-line">通用/由环境决定</span>'}</div><div class="item-sub deploy-message">${esc(p.description||'')}</div><div class="row end"><button class="btn mini" onclick="setPage('部署资源')">配置资源</button>${p.id==='rockchip'?(state.deployHostOs==='windows'?'<button class="btn mini primary" onclick="setPage(\'部署资源\')">配置 Linux / WSL2 节点</button>':'<button class="btn mini primary" onclick="openRknnSdkInstallerV41()">安装官方 SDK</button>'):''}</div></div>`;
  }
  window.renderDeployPluginsV41=async()=>{
    document.getElementById('view').innerHTML=`<section class="panel"><div class="panel-head"><div><div class="panel-title">部署插件</div><div class="subline">平台适配层调用厂商官方 SDK / 编译器</div></div><button class="btn" onclick="renderDeployPluginsV41()">重新检测</button></div><div class="panel-body" id="pluginGridV41"><div class="loading">正在检测插件...</div></div></section>`;
    await loadDeployPluginsV41();const box=document.getElementById('pluginGridV41');if(box)box.innerHTML=`<div class="deploy-resource-grid">${state.deployPlugins.map(pluginCard).join('')}</div>`;
  };
  window.openRknnSdkInstallerV41=async()=>{
    if(!state.deployLoaded)await loadDeployData(true);
    const rows=(state.deployResources||[]).filter(r=>r.kind==='rockchip'&&r.mode!=='remote'&&!r.builtin);
    modal('安装 RKNN-Toolkit2',`<div class="form"><div class="field"><label>瑞芯微部署资源</label><select id="rknnInstallResource" class="select">${rows.map(r=>`<option value="${r.id}">${esc(r.name)} · ${esc(r.python_path||'平台 Python')}</option>`).join('')||'<option value="">请先创建瑞芯微本机部署资源</option>'}</select></div><div class="field"><label>官方 Wheel 文件</label><input id="rknnWheelPath" class="input" placeholder="例如 /opt/sdk/rknn_toolkit2-2.3.2-cp310-...whl"></div><button class="btn primary" onclick="installRknnSdkV41()" ${rows.length?'':'disabled'}>安装并检测</button><div id="rknnInstallResult"></div></div>`,true);
  };
  window.installRknnSdkV41=async()=>{const rid=document.getElementById('rknnInstallResource')?.value||'',wheel=document.getElementById('rknnWheelPath')?.value||'';if(!rid||!wheel)return toast('请选择资源并填写官方 wheel 路径');const box=document.getElementById('rknnInstallResult');if(box)box.innerHTML='<div class="loading">正在安装 RKNN-Toolkit2...</div>';try{const r=await api('/api/v41/deploy/plugins/rockchip/install-sdk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({resource_id:rid,wheel_path:wheel})});if(box)box.innerHTML=`<div class="alert ok">安装完成 · ${esc(r.resource?.version||'')}</div>`;toast('RKNN-Toolkit2 已安装')}catch(e){if(box)box.innerHTML=`<div class="alert err">${esc(e.message||e)}</div>`}};

  // Extend resource editor for Rockchip with isolated Python environment.
  const oldOpen=window.openDeployResourceModal, oldEdit=window.editDeployResource;
  function addRockchipOption(){const k=document.getElementById('drKind');if(k&&!k.querySelector('option[value="rockchip"]')){const o=document.createElement('option');o.value='rockchip';o.textContent='瑞芯微 RKNN-Toolkit2';k.insertBefore(o,k.firstChild)}}
  window.openDeployResourceModal=()=>{oldOpen();addRockchipOption()};
  window.editDeployResource=id=>{oldEdit(id);addRockchipOption();const r=(state.deployResources||[]).find(x=>x.id===id);if(r?.kind==='rockchip'){const k=document.getElementById('drKind');if(k)k.value='rockchip';toggleDeployResourceFields()}};
})();

// ============================================================
// v42: 简单操作 + 持续迭代闭环
// ============================================================
(function(){
  const V42='42.24.0';
  state.v42={templates:[],sources:[],policies:[],runs:[],quality:null,blueprints:[],loaded:false};
  const oldRender42=render, oldNav42=renderNav, oldTop42=renderTop;
  const CORE_MENUS=[
    {title:'算法生产',items:['工作台','新建算法','算法列表','自动迭代']},
    {title:'数据中心',items:['素材接入','数据集','自动标注']},
    {title:'训练与质检',items:['训练任务','质量中心','检测台','测试发布']},
    {title:'部署中心',items:['部署转换','部署产物']},
    {title:'配置中心',items:['模型配置','训练资源','部署资源','部署插件','组件检测']},
  ];
  const EXTRA_ICON={
    '新建算法':'<path d="M12 3v18M3 12h18"/><circle cx="12" cy="12" r="9"/>',
    '自动迭代':'<path d="M20 7h-6V1M4 17h6v6"/><path d="M18.5 4.5A9 9 0 0 0 4.8 7M5.5 19.5A9 9 0 0 0 19.2 17"/>',
    '素材接入':'<path d="M4 5h16v14H4z"/><path d="m7 15 3-3 2 2 3-4 2 3M8 8h.01"/>',
    '质量中心':'<path d="M4 18V9M10 18V5M16 18v-7M22 18V3"/><path d="M2 21h21"/>',
  };
  function icon42(n){if(EXTRA_ICON[n])return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${EXTRA_ICON[n]}</svg>`;try{return menuIcon(n)}catch(e){return '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor"/></svg>'}}
  renderNav=function(){
    const projectName=esc(state.project?.name||'默认空间');
    document.getElementById('nav').innerHTML=`<div class="nav-project"><div class="nav-project-k">当前项目</div><div class="nav-project-v" title="${projectName}">${projectName}</div></div>${CORE_MENUS.map(g=>`<div class="nav-group"><div class="nav-group-title">${g.title}</div>${g.items.map(n=>`<button class="nav-btn ${state.page===n?'active':''}" title="${n}" onclick="setPage('${n}')"><span class="nav-left"><i>${icon42(n)}</i><b>${n}</b></span><span class="nav-arrow">›</span></button>`).join('')}</div>`).join('')}<div class="nav-footer"><span>版本</span><b>v${V42}</b></div>`;
  };
  const META42={
    '新建算法':['算法生产','从业务场景创建新算法，不要求先懂训练参数'],
    '自动迭代':['算法生产','线上抽查、补样、标注、重训和质量门禁'],
    '素材接入':['数据中心','接入目录、视频流或业务系统接口'],
    '质量中心':['训练与质检','数据质量与模型指标统一检查'],
  };
  renderTop=function(){oldTop42();const m=META42[state.page];if(m){document.getElementById('crumb').textContent=m[0];document.getElementById('title').textContent=state.page;document.getElementById('pageDesc').textContent=m[1]}const v=document.getElementById('versionBadge');if(v)v.textContent='v'+V42};

  async function load42(force=false){
    if(state.v42.loaded&&!force)return state.v42;
    const [t,s,p,r,q,b]=await Promise.all([
      safe(api('/api/v42/industry-templates')),
      safe(api(`/api/v42/projects/${pid()}/sources`)),
      safe(api(`/api/v42/projects/${pid()}/iteration-policies`)),
      safe(api(`/api/v42/projects/${pid()}/iteration-runs`)),
      safe(api(`/api/v42/projects/${pid()}/quality-overview`)),
      safe(api(`/api/v42/projects/${pid()}/algorithm-blueprints`)),
    ]);
    state.v42.templates=t?.items||[];state.v42.sources=s?.items||[];state.v42.policies=p?.items||[];state.v42.runs=r?.items||[];state.v42.quality=q||null;state.v42.blueprints=b?.items||[];state.v42.loaded=true;return state.v42;
  }
  window.load42=load42;
  const fmtPct=v=>v==null?'-':(Number(v)*100).toFixed(1)+'%';
  const v42Status=s=>`<span class="pill ${['done','ready'].includes(s)?'ok':['failed'].includes(s)?'err':'warn'}">${esc(({queued:'排队中',running:'运行中',done:'已完成',failed:'失败',needs_attention:'待处理',ready:'可用',unchecked:'未检测'}[s]||s||'-'))}</span>`;

  window.renderNewAlgorithmV42=async function(){
    await load42();
    document.getElementById('view').innerHTML=`<section class="v42-wizard-head"><div><div class="hero-k">训练新算法</div><h2>先说要解决什么问题，训练参数交给系统</h2><p>可选行业模板，也可以完全自定义。模板只提供数据策略，不限制你训练市面上已有的普通算法。</p></div><div class="v42-stepbar"><span class="active">1 业务目标</span><span>2 标签与场景</span><span>3 准备数据</span><span>4 自动训练</span></div></section>
      <section class="panel"><div class="panel-head"><div><div class="panel-title">选择业务模板</div><div class="subline">选模板是为了给数据准备建议，不锁死算法类型</div></div></div><div class="panel-body"><div class="v42-template-grid">${state.v42.templates.map((t,i)=>`<button class="v42-template ${i===0?'selected':''}" data-tpl="${t.id}" onclick="pickTemplate42('${t.id}',this)"><span>${esc(t.industry)}</span><b>${esc(t.name)}</b><small>重点：${esc(t.focus)}</small></button>`).join('')}</div></div></section>
      <section class="panel"><div class="panel-head"><div class="panel-title">算法定义</div></div><div class="panel-body"><div class="form two"><div class="field"><label>算法名称</label><input id="a42Name" class="input" placeholder="例如：宗教场所夜间人员离床检测"></div><div class="field"><label>行业 / 场景</label><input id="a42Industry" class="input" placeholder="例如：监所 / 宗教场所 / 工业园区"></div><div class="field full"><label>要识别的标签</label><input id="a42Labels" class="input" placeholder="多个标签用逗号分隔，例如 person, helmet"></div><div class="field full"><label>必须覆盖的重点场景</label><textarea id="a42Focus" class="textarea" placeholder="例如：夜间、逆光、远距离、遮挡、小目标"></textarea></div><div class="field full"><label>容易误报的反例 / 负样本</label><textarea id="a42Negative" class="textarea" placeholder="例如：海报人像、反光、蒸汽、坐地但并非倒地"></textarea></div><div class="field full"><label>备注</label><input id="a42Remark" class="input" placeholder="选填"></div></div><div class="row end"><button class="btn primary" onclick="createBlueprint42()">创建算法并进入准备数据</button></div></div></section>`;
    const first=state.v42.templates[0];if(first)setTimeout(()=>fillTemplate42(first),20);
  };
  window.fillTemplate42=t=>{const val=(id,v)=>{const e=document.getElementById(id);if(e)e.value=v||''};val('a42Industry',t.industry);val('a42Name',t.name);val('a42Labels',(t.labels||[]).join(', '));val('a42Focus',t.focus);val('a42Negative',t.negative);state.v42.templateId=t.id};
  window.pickTemplate42=(id,el)=>{document.querySelectorAll('.v42-template').forEach(x=>x.classList.remove('selected'));el?.classList.add('selected');const t=state.v42.templates.find(x=>x.id===id);if(t)fillTemplate42(t)};
  window.createBlueprint42=async()=>{const labels=(document.getElementById('a42Labels')?.value||'').split(/[,，\n]/).map(x=>x.trim()).filter(Boolean);try{await api(`/api/v42/projects/${pid()}/algorithm-blueprints`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:document.getElementById('a42Name')?.value||'',industry:document.getElementById('a42Industry')?.value||'',template_id:state.v42.templateId||'custom',labels,focus_scenes:document.getElementById('a42Focus')?.value||'',negative_scenes:document.getElementById('a42Negative')?.value||'',remark:document.getElementById('a42Remark')?.value||''})});state.v42.loaded=false;await loadAll();toast('算法已创建');setPage('素材接入')}catch(e){toast(e.message||e)}};

  function sourceTypeName(t){return ({folder:'本机/共享目录',rtsp:'视频流 / RTSP',http_json:'业务系统 API'}[t]||t)}
  window.renderSourcesV42=async function(){await load42(true);document.getElementById('view').innerHTML=`<section class="v42-source-hero"><div><h2>素材从哪里来？</h2><p>图片、视频、摄像头和其他业务系统都统一进入数据集。采集只负责取真实素材，不会伪造标注。</p></div><div class="row"><button class="btn" onclick="setPage('数据集')">上传图片 / 标注包</button><button class="btn" onclick="setPage('视频切帧')">上传视频切帧</button><button class="btn primary" onclick="openSource42()">新增自动素材源</button></div></section><section class="panel"><div class="panel-head"><div class="panel-title">自动素材源</div></div><div class="panel-body"><div class="v42-source-grid">${state.v42.sources.map(s=>`<div class="v42-source-card"><div class="row between"><div><b>${esc(s.name)}</b><div class="item-sub">${esc(sourceTypeName(s.type))}</div></div>${v42Status(s.status)}</div><div class="v42-source-url">${esc(s.source)}</div><div class="row end"><button class="btn mini" onclick="testSource42('${s.id}')">检测</button><button class="btn mini primary" onclick="collectSource42('${s.id}')">采集素材</button><button class="btn mini danger" onclick="deleteSource42('${s.id}')">删除</button></div></div>`).join('')||'<div class="empty">还没有自动素材源。你仍然可以直接上传图片或视频。</div>'}</div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">接入方式</div></div><div class="panel-body"><div class="v42-three"><div><b>视频 / 摄像头</b><span>RTSP、网络视频或上传视频，按时间间隔自动抽帧。</span></div><div><b>其他系统</b><span>HTTP JSON 接口返回图片地址，平台自动拉取到数据集。</span></div><div><b>本地素材库</b><span>指定本机或共享目录，批量读取图片。</span></div></div></div></section>`};
  window.openSource42=()=>modal('新增自动素材源',`<div class="form"><div class="field"><label>名称</label><input id="s42Name" class="input" placeholder="例如：居安思·烟火算法回流"></div><div class="field"><label>类型</label><select id="s42Type" class="select" onchange="toggleSource42()"><option value="rtsp">视频流 / RTSP / 网络视频</option><option value="folder">本机或共享目录</option><option value="http_json">业务系统 HTTP JSON API</option></select></div><div class="field"><label>来源地址</label><input id="s42Source" class="input" placeholder="rtsp://...、本机目录或 https://.../api/images"></div><div id="s42Http" style="display:none"><div class="field"><label>请求 Headers（JSON，可空）</label><textarea id="s42Headers" class="textarea">{}</textarea></div><div class="grid2-mini"><div class="field"><label>列表路径</label><input id="s42Items" class="input" value="items"></div><div class="field"><label>图片URL字段</label><input id="s42Field" class="input" value="image_url"></div></div></div><button class="btn primary" onclick="saveSource42()">保存</button></div>`,true);
  window.toggleSource42=()=>{const b=document.getElementById('s42Http');if(b)b.style.display=document.getElementById('s42Type')?.value==='http_json'?'block':'none'};
  window.saveSource42=async()=>{try{await api(`/api/v42/projects/${pid()}/sources`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:document.getElementById('s42Name')?.value||'',type:document.getElementById('s42Type')?.value||'rtsp',source:document.getElementById('s42Source')?.value||'',headers_json:document.getElementById('s42Headers')?.value||'{}',items_path:document.getElementById('s42Items')?.value||'items',image_url_field:document.getElementById('s42Field')?.value||'image_url'})});closeModal();state.v42.loaded=false;renderSourcesV42();toast('素材源已保存')}catch(e){toast(e.message||e)}};
  window.testSource42=async id=>{try{const r=await api(`/api/v42/projects/${pid()}/sources/${id}/test`,{method:'POST'});toast(r.message||'检测成功');state.v42.loaded=false;renderSourcesV42()}catch(e){toast(e.message||e)}};
  window.deleteSource42=async id=>{if(!confirm('删除这个素材源？不会删除已导入的数据。'))return;await api(`/api/v42/projects/${pid()}/sources/${id}`,{method:'DELETE'});state.v42.loaded=false;renderSourcesV42()};
  window.collectSource42=async id=>{await load42();modal('采集素材',`<div class="form"><div class="field"><label>放入数据集</label><select id="c42Ds" class="select">${(state.datasets||[]).map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div><div class="grid2-mini"><div class="field"><label>本次最多采集</label><input id="c42Max" class="input" value="100"></div><div class="field"><label>视频抽帧间隔（秒）</label><input id="c42Interval" class="input" value="2"></div></div><button class="btn primary" onclick="startCollect42('${id}')">开始采集</button></div>`)};
  window.startCollect42=async id=>{try{await api(`/api/v42/projects/${pid()}/sources/${id}/collect`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset_id:document.getElementById('c42Ds')?.value||'default',max_items:Number(document.getElementById('c42Max')?.value||100),interval_seconds:Number(document.getElementById('c42Interval')?.value||2)})});closeModal();toast('采集任务已启动，素材会进入数据集')}catch(e){toast(e.message||e)}};

  window.renderIterationV42=async function(){await load42(true);const policies=state.v42.policies,runs=state.v42.runs;document.getElementById('view').innerHTML=`<section class="v42-loop-hero"><div><div class="hero-k">持续迭代</div><h2>算法上线后，不是训练结束，而是下一轮数据来源</h2><p>低准确率 → 找问题 → 回流真实素材 → 标注 → 重训 → 再过质量门禁。</p></div><div class="row"><button class="btn" onclick="openAuditConnect42()">接入线上抽查</button><button class="btn primary" onclick="openPolicy42()">新建自动迭代策略</button></div></section><div class="v42-loopline"><span>线上算法</span><i>→</i><span>模型抽查 / 质量检查</span><i>→</i><span>低分样本回流</span><i>→</i><span>自动标注</span><i>→</i><span>自动重训</span><i>→</i><span>重新上线</span></div><section class="panel"><div class="panel-head"><div class="panel-title">迭代策略</div></div><div class="panel-body"><div class="card-list">${policies.map(p=>{const a=(state.algorithms||[]).find(x=>x.id===p.algorithm_id),s=state.v42.sources.find(x=>x.id===p.source_id);return `<div class="v42-policy"><div class="grow"><div class="row"><b>${esc(p.name)}</b><span class="pill ok">启用</span></div><div class="item-sub">${esc(a?.name||'未绑定算法')} · 数据集 ${esc((state.datasets||[]).find(x=>x.id===p.dataset_id)?.name||p.dataset_id)} · 素材源 ${esc(s?.name||'未配置')}</div><div class="v42-gates"><span>Precision ≥ ${fmtPct(p.min_precision)}</span><span>Recall ≥ ${fmtPct(p.min_recall)}</span><span>mAP50 ≥ ${fmtPct(p.min_map50)}</span><span>单标签 ≥ ${p.min_boxes_per_label} 框</span>${p.use_online_audit?`<span>线上准确率 ≥ ${fmtPct(p.min_online_accuracy)} / ${p.min_audit_samples}样本</span>`:''}</div></div><div class="row"><button class="btn small primary" onclick="runPolicy42('${p.id}')">立即运行</button><button class="btn small danger" onclick="deletePolicy42('${p.id}')">删除</button></div></div>`}).join('')||'<div class="empty">暂无策略。建议为已经上线或准备上线的算法创建一条质量门禁。</div>'}</div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">最近迭代记录</div><button class="btn small" onclick="renderIterationV42()">刷新</button></div><div class="panel-body"><table class="table"><thead><tr><th>策略</th><th>状态</th><th>当前阶段</th><th>轮次</th><th>结果</th></tr></thead><tbody>${runs.map(r=>`<tr><td>${esc(r.policy_name)}</td><td>${v42Status(r.status)}</td><td>${esc(r.stage||'-')}${r.error?`<div class="error-line">${esc(r.error)}</div>`:''}</td><td>${r.loop||0}</td><td>${esc(r.result||'-')}</td></tr>`).join('')||'<tr><td colspan="5">暂无迭代记录</td></tr>'}</tbody></table></div></section>`};
  window.openAuditConnect42=()=>modal('接入线上算法抽查',`<div class="form"><div class="callout"><b>适合接居安思、SaaS算法平台或独立大模型抽查服务</b><div>外部系统抽查完一条算法结果后，把“对/错、问题类型、原图URL”回传给本平台。错误样本可自动进入指定训练数据集，迭代策略再按线上准确率触发回炉。</div></div><div class="field"><label>回传接口</label><input class="input mono" readonly value="POST /api/v42/projects/${pid()}/online-feedback"></div><div class="field"><label>JSON 示例</label><textarea class="textarea mono" readonly>{
  "algorithm_id": "算法ID",
  "correct": false,
  "score": 0.42,
  "category": "夜间漏检",
  "reason": "逆光场景漏检",
  "image_url": "https://.../frame.jpg",
  "dataset_id": "default",
  "source": "居安思-大模型抽查"
}</textarea></div><div class="muted">系统不会自己假定抽查结论；结论必须来自真实外部系统或已配置的大模型服务。</div></div>`,true);

  window.openPolicy42=async()=>{await load42();modal('新建自动迭代策略',`<div class="form"><div class="field"><label>策略名称</label><input id="p42Name" class="input" placeholder="例如：烟火算法线上低准确率自动回炉"></div><div class="grid2-mini"><div class="field"><label>算法</label><select id="p42Alg" class="select">${(state.algorithms||[]).map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></div><div class="field"><label>训练数据集</label><select id="p42Ds" class="select">${(state.datasets||[]).map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select></div></div><div class="field"><label>低分时从哪里补素材</label><select id="p42Source" class="select"><option value="">不自动补素材</option>${state.v42.sources.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join('')}</select></div><div class="v42-rulebox"><b>达标线</b><div class="grid3"><div class="field"><label>Precision</label><input id="p42P" class="input" value="0.85"></div><div class="field"><label>Recall</label><input id="p42R" class="input" value="0.80"></div><div class="field"><label>mAP50</label><input id="p42M" class="input" value="0.85"></div></div><div class="grid3"><div class="field"><label>最少图片</label><input id="p42Imgs" class="input" value="300"></div><div class="field"><label>每标签最少框</label><input id="p42Boxes" class="input" value="100"></div><div class="field"><label>最多自动迭代</label><input id="p42Loops" class="input" value="2"></div></div></div><details class="advanced"><summary>高级：自动标注与重训参数</summary><div class="grid2-mini"><div class="field"><label>自动标注模型</label><select id="p42ModelCfg" class="select"><option value="">不自动标注</option>${(state.modelConfigs||[]).map(m=>`<option value="${m.id}">${esc(m.name)}</option>`).join('')}</select></div><div class="field"><label>重点标签</label><input id="p42Label" class="input" placeholder="如 fire；留空则优先缺样本标签"></div><div class="field"><label>基础模型</label><input id="p42Base" class="input" value="yolo11s.pt"></div><div class="field"><label>训练轮次</label><input id="p42Epochs" class="input" value="80"></div></div><div class="v42-audit-toggle"><label><input id="p42Audit" type="checkbox"> 把线上抽查准确率也作为达标门禁</label><div class="grid2-mini"><div class="field"><label>最少抽查样本</label><input id="p42AuditN" class="input" value="20"></div><div class="field"><label>线上准确率下限</label><input id="p42AuditAcc" class="input" value="0.90"></div></div></div></details><button class="btn primary" onclick="savePolicy42()">保存策略</button></div>`,true)};
  window.savePolicy42=async()=>{const modelCfg=document.getElementById('p42ModelCfg')?.value||'';try{await api(`/api/v42/projects/${pid()}/iteration-policies`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:document.getElementById('p42Name')?.value||'',algorithm_id:document.getElementById('p42Alg')?.value||'',dataset_id:document.getElementById('p42Ds')?.value||'default',source_id:document.getElementById('p42Source')?.value||'',min_images:Number(document.getElementById('p42Imgs')?.value||300),min_boxes_per_label:Number(document.getElementById('p42Boxes')?.value||100),min_precision:Number(document.getElementById('p42P')?.value||.85),min_recall:Number(document.getElementById('p42R')?.value||.8),min_map50:Number(document.getElementById('p42M')?.value||.85),use_online_audit:!!document.getElementById('p42Audit')?.checked,min_audit_samples:Number(document.getElementById('p42AuditN')?.value||20),min_online_accuracy:Number(document.getElementById('p42AuditAcc')?.value||.9),max_loops:Number(document.getElementById('p42Loops')?.value||2),auto_collect:!!document.getElementById('p42Source')?.value,collect_each_loop:100,auto_prelabel:!!modelCfg,model_config_id:modelCfg,target_label:document.getElementById('p42Label')?.value||'',auto_retrain:true,framework:'ultralytics',algorithm:'yolo11s_det',model:document.getElementById('p42Base')?.value||'yolo11s.pt',epochs:Number(document.getElementById('p42Epochs')?.value||80),imgsz:640,batch:8,device:'0',target:'local'})});closeModal();state.v42.loaded=false;renderIterationV42();toast('迭代策略已保存')}catch(e){toast(e.message||e)}};
  window.runPolicy42=async id=>{try{await api(`/api/v42/projects/${pid()}/iteration-policies/${id}/run`,{method:'POST'});toast('自动迭代已启动');setTimeout(()=>renderIterationV42(),900)}catch(e){toast(e.message||e)}};
  window.deletePolicy42=async id=>{if(!confirm('删除这条迭代策略？'))return;await api(`/api/v42/projects/${pid()}/iteration-policies/${id}`,{method:'DELETE'});state.v42.loaded=false;renderIterationV42()};

  window.renderQualityV42=async function(){await load42(true);const q=state.v42.quality||{datasets:[],algorithms:[]};document.getElementById('view').innerHTML=`<section class="v42-quality-head"><div><h2>质量中心</h2><p>“准确率”拆成 Precision、Recall、mAP；数据同时检查数量、标签覆盖和有效标注。</p></div><button class="btn" onclick="renderQualityV42()">重新检查</button></section><section class="panel"><div class="panel-head"><div class="panel-title">数据质量</div></div><div class="panel-body"><div class="v42-quality-grid">${q.datasets.map(d=>{const x=d.quality||{},use=x.label_usage||{};return `<div class="v42-quality-card"><div class="row between"><b>${esc(d.name)}</b><span class="pill ${x.can_train?'ok':'err'}">${x.can_train?'可训练':'需处理'}</span></div><div class="v42-bigmetric"><b>${x.image_count||0}</b><span>图片</span><b>${x.box_count||0}</b><span>标注框</span></div><div class="v42-hygiene"><span>重复 ${d.hygiene?.duplicate_count||0}</span><span>疑似模糊 ${d.hygiene?.blurry_count||0}</span><span>低分辨率 ${d.hygiene?.low_resolution_count||0}</span><span>损坏 ${d.hygiene?.broken_count||0}</span></div><div class="label-bars">${Object.entries(use).map(([k,v])=>`<div><span>${esc(k)}</span><b>${v}</b></div>`).join('')}</div>${(x.warnings||[]).length?`<div class="warn-list">${x.warnings.map(w=>`<span>${esc(w)}</span>`).join('')}</div>`:''}</div>`}).join('')||'<div class="empty">暂无数据集</div>'}</div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">算法质量</div></div><div class="panel-body"><table class="table"><thead><tr><th>算法</th><th>Precision</th><th>Recall</th><th>mAP50</th><th>线上抽查</th><th>训练来源</th></tr></thead><tbody>${q.algorithms.map(a=>`<tr><td><b>${esc(a.name)}</b><div class="item-sub">${a.versions||0} 个版本</div></td><td>${fmtPct(a.metrics?.precision)}</td><td>${fmtPct(a.metrics?.recall)}</td><td>${fmtPct(a.metrics?.map50)}</td><td>${a.online_audit?.total?`${fmtPct(a.online_audit.accuracy)} <span class="item-sub">${a.online_audit.total}条</span>`:'未接入'}</td><td>${a.job_id?esc(a.job_id):'尚无可读取训练指标'}</td></tr>`).join('')||'<tr><td colspan="6">暂无算法</td></tr>'}</tbody></table></div></section>`};

  // v42.1：统计驾驶舱。只使用真实项目、数据集、训练任务和评测数据。
  const oldDashboard42=window.renderHomeDashboard;
  const fmtNum42=n=>Number(n||0).toLocaleString('zh-CN');
  const fmtHours42=sec=>{sec=Math.max(0,Number(sec||0));const h=sec/3600;if(h>=1000)return (h/1000).toFixed(1)+'k h';if(h>=10)return h.toFixed(1)+' h';if(h>=1)return h.toFixed(2)+' h';return Math.round(sec/60)+' min'};
  const jobDuration42=j=>{const parse=v=>{const d=v?new Date(String(v).replace(' ','T')):null;return d&&!Number.isNaN(d.getTime())?d:null};const a=parse(j.started_at||j.created_at);if(!a)return 0;const terminal=['done','finished','completed','failed','stopped'].includes(j.status);const b=terminal?(parse(j.finished_at||j.updated_at)||new Date()):new Date();return Math.max(0,(b-a)/1000)};
  function dashboardData42(){
    const algs=state.algorithms||[], jobs=state.jobs||[], dss=state.datasets||[], blue=state.v42?.blueprints||[];
    const versions=algs.reduce((n,a)=>n+(a.versions||[]).length,0);
    const trained=algs.filter(a=>(a.versions||[]).length>0).length;
    const running=jobs.filter(j=>j.status==='running').length, queued=jobs.filter(j=>j.status==='queued').length;
    const doneJobs=jobs.filter(j=>['done','finished','completed'].includes(j.status)), failed=jobs.filter(j=>j.status==='failed').length;
    const totalSeconds=jobs.reduce((n,j)=>n+jobDuration42(j),0), avgSeconds=doneJobs.length?doneJobs.reduce((n,j)=>n+jobDuration42(j),0)/doneJobs.length:0;
    const successRate=(doneJobs.length+failed)>0?doneJobs.length/(doneJobs.length+failed):0;
    const totalImages=dss.reduce((n,d)=>n+Number(d.images||0),0), annotated=dss.reduce((n,d)=>n+Number(d.annotated_images||0),0), boxes=dss.reduce((n,d)=>n+Number(d.boxes||0),0);
    const dsKinds={全标注:0,混合:0,未标注:0,空数据集:0};
    dss.forEach(d=>{const im=Number(d.images||0),an=Number(d.annotated_images||0);if(!im)dsKinds['空数据集']++;else if(an===im)dsKinds['全标注']++;else if(an>0)dsKinds['混合']++;else dsKinds['未标注']++});
    const industryById=new Map(blue.map(b=>[b.algorithm_id,(b.industry||'').trim()||'未分类']));
    const cat={};algs.forEach(a=>{const k=industryById.get(a.id)||'未分类';cat[k]=(cat[k]||0)+1});
    const catRows=Object.entries(cat).sort((a,b)=>b[1]-a[1]);
    const q=state.v42?.quality||{}, measured=(q.algorithms||[]).map(a=>a.metrics||{}).filter(m=>m.map50!=null||m.precision!=null||m.recall!=null);
    const mean=k=>{const vals=measured.map(m=>Number(m[k])).filter(Number.isFinite);return vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:null};
    const maps=measured.map(m=>Number(m.map50)).filter(Number.isFinite), bestMap=maps.length?Math.max(...maps):null;
    const ready=(state.targets||[]).filter(x=>x.status==='ready').length;
    const iruns=state.v42?.runs||[], iterRunning=iruns.filter(x=>['queued','running'].includes(x.status)).length;
    const days=[];for(let i=6;i>=0;i--){const d=new Date();d.setHours(0,0,0,0);d.setDate(d.getDate()-i);const key=d.toISOString().slice(0,10);const rows=jobs.filter(j=>String(j.created_at||'').slice(0,10)===key);days.push({key,label:(d.getMonth()+1)+'/'+d.getDate(),count:rows.length,hours:rows.reduce((n,j)=>n+jobDuration42(j),0)/3600})}
    return {algs,versions,trained,running,queued,done:doneJobs.length,failed,totalSeconds,avgSeconds,successRate,dss,totalImages,annotated,boxes,dsKinds,catRows,meanP:mean('precision'),meanR:mean('recall'),meanM:mean('map50'),bestMap,measured:measured.length,ready,iterRunning,days,jobs};
  }
  function dashPct42(v){return v==null?'-':(Number(v)*100).toFixed(1)+'%'}
  function renderDashboardBody42(){
    const d=dashboardData42(), maxDay=Math.max(1,...d.days.map(x=>x.count));
    const categoryHtml=d.catRows.length?d.catRows.slice(0,6).map(([k,v])=>`<div class="dash-rank-row"><span>${esc(k)}</span><i><b style="width:${Math.max(8,v/Math.max(1,d.algs.length)*100)}%"></b></i><strong>${v}</strong></div>`).join(''):'<div class="dash-empty">暂无分类数据</div>';
    const datasetHtml=Object.entries(d.dsKinds).map(([k,v])=>`<div class="dash-ds-chip"><span>${k}</span><b>${v}</b></div>`).join('');
    const recent=d.jobs.slice(0,6).map(j=>`<tr><td><b>${esc(j.run_name||j.algorithm_name||j.name||j.id)}</b><small>${esc(j.framework||'')}</small></td><td><span class="pill ${['done','finished','completed'].includes(j.status)?'ok':j.status==='failed'?'err':'warn'}">${esc(statusName(j.status))}</span></td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td>${fmtHours422(jobDuration422(j))}</td><td>${j.progress_percent!=null?Math.round(j.progress_percent)+'%':'-'}</td></tr>`).join('')||'<tr><td colspan="5">暂无训练记录</td></tr>';
    document.getElementById('view').innerHTML=`<div class="dash421">
      <section class="dash421-hero"><div class="dash421-brand"><span>ALGORITHM OPS</span><b>畅联云算法训练</b></div><div class="dash421-actions"><button class="btn dash-dark-btn" onclick="setPage('新建算法')">新建算法</button><button class="btn dash-dark-btn" onclick="setPage('训练任务')">训练任务</button></div></section>
      <section class="dash421-kpis">
        <div class="dash421-kpi"><span>算法分类</span><b>${d.catRows.length}</b><em>${d.catRows.slice(0,2).map(x=>esc(x[0])).join(' · ')||'未分类'}</em></div>
        <div class="dash421-kpi"><span>算法总数</span><b>${fmtNum42(d.algs.length)}</b><em>已训练 ${d.trained} · 版本 ${d.versions}</em></div>
        <div class="dash421-kpi hot"><span>正在训练</span><b>${d.running}</b><em>排队 ${d.queued}</em></div>
        <div class="dash421-kpi"><span>数据集</span><b>${fmtNum42(d.dss.length)}</b><em>${fmtNum42(d.totalImages)} 张素材</em></div>
        <div class="dash421-kpi"><span>训练总时长</span><b>${fmtHours422(d.totalSeconds)}</b><em>累计 ${d.jobs.length} 次</em></div>
        <div class="dash421-kpi"><span>平均训练时长</span><b>${fmtHours422(d.avgSeconds)}</b><em>成功率 ${(d.successRate*100).toFixed(1)}%</em></div>
      </section>
      <section class="dash421-grid top-grid">
        <div class="dash421-card trend-card"><div class="dash421-card-head"><b>近 7 天训练趋势</b><span>${d.done} 已完成 · ${d.failed} 失败</span></div><div class="dash421-bars">${d.days.map(x=>`<div class="dash421-bar"><i style="height:${Math.max(4,x.count/maxDay*100)}%"></i><b>${x.count}</b><span>${x.label}</span></div>`).join('')}</div></div>
        <div class="dash421-card"><div class="dash421-card-head"><b>算法分类</b><span>${d.catRows.length} 类</span></div><div class="dash-rank">${categoryHtml}</div></div>
        <div class="dash421-card"><div class="dash421-card-head"><b>数据集分类</b><span>标注率 ${d.totalImages?((d.annotated/d.totalImages)*100).toFixed(1):'0.0'}%</span></div><div class="dash-ds-grid">${datasetHtml}</div><div class="dash-inline-metrics"><div><span>图片</span><b>${fmtNum42(d.totalImages)}</b></div><div><span>已标注</span><b>${fmtNum42(d.annotated)}</b></div><div><span>标注框</span><b>${fmtNum42(d.boxes)}</b></div></div></div>
      </section>
      <section class="dash421-grid quality-grid">
        <div class="dash421-card quality-card"><div class="dash421-card-head"><b>算法质量</b><span>${d.measured} 个算法有指标</span></div><div class="dash-quality-metrics"><div><span>平均 Precision</span><b>${dashPct42(d.meanP)}</b></div><div><span>平均 Recall</span><b>${dashPct42(d.meanR)}</b></div><div><span>平均 mAP50</span><b>${dashPct42(d.meanM)}</b></div><div><span>最高 mAP50</span><b>${dashPct42(d.bestMap)}</b></div></div></div>
        <div class="dash421-card resource-card"><div class="dash421-card-head"><b>运行状态</b><span>实时</span></div><div class="dash-status-grid"><div><i class="dot-live ok"></i><span>可用训练资源</span><b>${d.ready}</b></div><div><i class="dot-live"></i><span>训练中</span><b>${d.running}</b></div><div><i class="dot-live warn"></i><span>自动迭代中</span><b>${d.iterRunning}</b></div><div><i class="dot-live err"></i><span>失败训练</span><b>${d.failed}</b></div></div></div>
      </section>
      <section class="dash421-card recent-card"><div class="dash421-card-head"><b>最近训练</b><button class="btn mini" onclick="setPage('训练任务')">全部</button></div><div class="table-wrap"><table class="table dash-table"><thead><tr><th>训练任务</th><th>状态</th><th>数据集</th><th>训练时长</th><th>进度</th></tr></thead><tbody>${recent}</tbody></table></div></section>
    </div>`;
  }
  window.renderHomeDashboard=renderHomeDashboard=function(){renderDashboardBody42();if(!state.v42?.loaded){load42().then(()=>{if(state.page==='工作台')renderDashboardBody42()})}};

  render=function(){
    state.versionInfo={...(state.versionInfo||{}),version:V42};
    if(state.page==='新建算法'){renderNav();renderTop();renderSummary();renderNewAlgorithmV42();return}
    if(state.page==='素材接入'){renderNav();renderTop();renderSummary();renderSourcesV42();return}
    if(state.page==='自动迭代'){renderNav();renderTop();renderSummary();renderIterationV42();return}
    if(state.page==='质量中心'){renderNav();renderTop();renderSummary();renderQualityV42();return}
    oldRender42();
  };
})();

// ============================================================
// v42.1 final UI cleanup: brand + remove tutorial/helper copy.
// ============================================================
(function(){
  const V='42.24.0';
  const baseTop=renderTop;
  renderTop=function(){
    baseTop();
    const desc=document.getElementById('pageDesc'); if(desc) desc.textContent='';
    const v=document.getElementById('versionBadge'); if(v) v.textContent='v'+V;
    const brand=document.querySelector('.brand-name'); if(brand) brand.textContent='畅联云算法训练';
    const logo=document.querySelector('.brand-logo'); if(logo) logo.textContent='CL';
  };
  renderSummary=function(){const box=document.getElementById('summary');if(box){box.classList.add('is-hidden');box.innerHTML=''}};
  function simplifyEmpty(el){
    const t=(el.textContent||'').trim();
    if(!t)return;
    if(/请先|先创建|建议|你仍然可以|点击|例如|需要先|请到/.test(t)){
      if(/模型/.test(t))el.textContent='暂无模型';
      else if(/任务|训练/.test(t))el.textContent='暂无任务';
      else if(/资源|环境/.test(t))el.textContent='暂无资源';
      else if(/算法|版本/.test(t))el.textContent='暂无算法';
      else el.textContent='暂无数据';
    }
  }
  function cleanup(root){
    if(!root||!root.querySelectorAll)return;
    window.beautifyFileInputs426?.(root);
    const wrapTable=table=>{if(!table.parentElement?.classList.contains('table-wrap')){const wrap=document.createElement('div');wrap.className='table-wrap';table.parentNode?.insertBefore(wrap,table);wrap.appendChild(table)}};
    if(root.matches?.('table.table'))wrapTable(root);
    root.querySelectorAll('table.table').forEach(wrapTable);
    root.querySelectorAll('.subline,.compact-note,.callout,.import-box,.v42-stepbar,.v42-loopline,.v42-wizard-head').forEach(x=>x.remove());
    root.querySelectorAll('.v42-source-hero>div:first-child,.v42-quality-head>div:first-child,.v42-loop-hero>div:first-child').forEach(x=>x.remove());
    root.querySelectorAll('.panel').forEach(p=>{const t=p.querySelector('.panel-title')?.textContent?.trim();if(['接入方式','系统原则','一条主流程','快速入口','使用建议'].includes(t))p.remove()});
    root.querySelectorAll('.empty').forEach(simplifyEmpty);
    root.querySelectorAll('input[placeholder],textarea[placeholder]').forEach(el=>{const v=el.getAttribute('placeholder')||'';if(/^(例如|如：|如 |选填|多个|rtsp|http|[A-Za-z]:[\\/]|\\\\)/i.test(v))el.removeAttribute('placeholder')});
    const desc=document.getElementById('pageDesc');if(desc)desc.textContent='';
  }
  window.PostRenderNormalizationRuntime=Object.freeze({apply:cleanup});
})();

// ============================================================
// v42.2 — information architecture + usable sources + auto-label jobs
// ============================================================
(function(){
  const V422='42.24.0';
  state.source422Filters={q:'',type:'all',status:'all',mode:'all'};
  state.auto422Filters={q:'',status:'all',model:'all',dataset:'all'};
  state.auto422Images=[];
  

  const ICON422={
    '工作台':'<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>',
    '算法列表':'<path d="M5 5h14v14H5z"/><path d="M8 9h8M8 13h5"/>',
    '训练任务':'<path d="m8 5 11 7-11 7z"/>',
    '质量中心':'<path d="M4 18V9M10 18V5M16 18v-7M22 18V3"/><path d="M2 21h21"/>',
    '素材接入':'<path d="M4 5h16v14H4z"/><path d="m7 15 3-3 2 2 3-4 2 3"/>',
    '数据集':'<path d="M4 6h16v12H4z"/><path d="M8 10h8M8 14h5"/>',
    '视频切帧':'<path d="M4 6h12v12H4z"/><path d="m10 10 4 2-4 2zM18 8h2M18 12h2M18 16h2"/>',
    '自动标注':'<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><circle cx="12" cy="12" r="4"/><path d="m18 5 1 1M5 18l1 1M5 6l1-1M18 19l1-1"/>',
    '检测台':'<circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/>',
    '测试发布':'<path d="M12 3v12M7 8l5-5 5 5"/><path d="M5 15v5h14v-5"/>',
    '部署转换':'<path d="M4 7h10M10 3l4 4-4 4M20 17H10M14 13l-4 4 4 4"/>',
    '部署产物':'<path d="M4 4h16v16H4z"/><path d="M8 9h8M8 13h8M8 17h5"/>',
    '模型配置':'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.8 1.8 0 0 0 .36 1.98l.06.06-2.12 2.12-.06-.06a1.8 1.8 0 0 0-1.98-.36 1.8 1.8 0 0 0-1.08 1.65V21h-3v-.09A1.8 1.8 0 0 0 10.5 19.3a1.8 1.8 0 0 0-1.98.36l-.06.06-2.12-2.12.06-.06A1.8 1.8 0 0 0 6.76 15.5 1.8 1.8 0 0 0 5.1 14.4H5v-3h.1A1.8 1.8 0 0 0 6.7 10.3a1.8 1.8 0 0 0-.36-1.98l-.06-.06 2.12-2.12.06.06a1.8 1.8 0 0 0 1.98.36A1.8 1.8 0 0 0 11.5 4.9V4h3v.9a1.8 1.8 0 0 0 1.08 1.65 1.8 1.8 0 0 0 1.98-.36l.06-.06 2.12 2.12-.06.06a1.8 1.8 0 0 0-.36 1.98 1.8 1.8 0 0 0 1.65 1.08H21v3h-.09A1.8 1.8 0 0 0 19.4 15z"/>',
    '训练资源':'<path d="M4 5h16v14H4z"/><path d="M7 9h10M7 13h6"/>',
    '部署资源':'<path d="M4 4h16v6H4zM4 14h16v6H4z"/><circle cx="7" cy="7" r=".7"/><circle cx="7" cy="17" r=".7"/>',
    '部署插件':'<path d="M8 3v5H3v8h5v5h8v-5h5V8h-5V3z"/>',
    '组件检测':'<path d="m4 12 5 5L20 6"/>'
  };
  const MENU422=[
    {title:'总览',items:['工作台']},
    {title:'算法生产',items:['算法列表','训练任务','质量中心']},
    {title:'数据中心',items:['素材接入','数据集','视频切帧','自动标注']},
    {title:'测试评测',items:['检测台','测试发布']},
    {title:'部署中心',items:['部署转换','部署产物']},
    {title:'资源配置',items:['模型配置','训练资源','部署资源','部署插件','组件检测']}
  ];
  const META422={
    '工作台':['总览',''],'算法列表':['算法生产',''],'训练任务':['算法生产',''],'质量中心':['算法生产',''],
    '素材接入':['数据中心',''],'数据集':['数据中心',''],'视频切帧':['数据中心',''],'自动标注':['数据中心',''],
    '检测台':['测试评测',''],'测试发布':['测试评测',''],'部署转换':['部署中心',''],'部署产物':['部署中心',''],
    '模型配置':['资源配置',''],'训练资源':['资源配置',''],'部署资源':['资源配置',''],'部署插件':['资源配置',''],'组件检测':['资源配置','']
  };
  function icon422(name){const p=ICON422[name]||'<circle cx="12" cy="12" r="8"/>';return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`}
  renderNav=function(){
    const pn=esc(state.project?.name||'默认空间');
    document.getElementById('nav').innerHTML=`<div class="nav-project"><div class="nav-project-k">当前项目</div><div class="nav-project-v" title="${pn}">${pn}</div></div>${MENU422.map(g=>`<div class="nav-group"><div class="nav-group-title">${g.title}</div>${g.items.map(n=>`<button class="nav-btn ${state.page===n?'active':''}" onclick="setPage('${n}')"><span class="nav-left"><i>${icon422(n)}</i><b>${n}</b></span></button>`).join('')}</div>`).join('')}<div class="nav-footer"><span>版本</span><b>v${V422}</b></div>`;
  };
  const top422=renderTop;
  renderTop=function(){
    top422(); const m=META422[state.page]||['畅联云算法训练',''];
    document.getElementById('crumb').textContent=m[0]; document.getElementById('title').textContent=state.page;
    const d=document.getElementById('pageDesc'); if(d)d.textContent=''; const v=document.getElementById('versionBadge');if(v)v.textContent='v'+V422;
  };

  function fmt422(v){return Number(v||0).toLocaleString('zh-CN')}
  function pct423(v){if(v==null||Number.isNaN(Number(v)))return '-';const n=Number(v);return (n>1?n:n*100).toFixed(1)+'%'}
  function dt423(v){return v?String(v).replace('T',' ').slice(0,19):'-'}
  function status423(s){const names={queued:'排队中',running:'运行中',done:'已完成',finished:'已完成',completed:'已完成',failed:'失败',stopped:'已停止',ready:'正常',unchecked:'未检测',disabled:'已停用'};const cls=['done','finished','completed','ready'].includes(s)?'ok':s==='failed'?'err':'warn';return `<span class="pill ${cls}">${esc(names[s]||s||'-')}</span>`}
  async function loadBlueprints423(){const r=await safe(api(`/api/v42/projects/${pid()}/algorithm-blueprints`));state.v42.blueprints=r?.items||[];return state.v42.blueprints}
  async function loadSourcesOnly422(){const r=await safe(api(`/api/v42/projects/${pid()}/sources`));state.v42.sources=r?.items||[];return state.v42.sources}
  function versionMetric422(a,key){const v=(a.versions||[])[0]||{};const rep=v.report||{};for(const [k,val] of Object.entries(rep)){const low=String(k).toLowerCase().replace(/\s+/g,'');if(key==='precision'&&low.includes('precision')){const n=Number(val);if(Number.isFinite(n))return n}if(key==='recall'&&low.includes('recall')){const n=Number(val);if(Number.isFinite(n))return n}if(key==='map50'&&low.includes('map50')&&!low.includes('95')){const n=Number(val);if(Number.isFinite(n))return n}}return null}
  function jobDuration422(j){const parse=v=>{const d=v?new Date(String(v).replace(' ','T')):null;return d&&!Number.isNaN(d.getTime())?d:null};const a=parse(j.started_at||j.created_at);if(!a)return 0;const terminal=['done','finished','completed','failed','stopped'].includes(j.status);const b=terminal?(parse(j.finished_at||j.updated_at)||new Date()):new Date();return Math.max(0,(b-a)/1000)}
  function fmtHours422(sec){sec=Math.max(0,Number(sec||0));const h=sec/3600;if(h>=1000)return (h/1000).toFixed(1)+'k h';if(h>=10)return h.toFixed(1)+' h';if(h>=1)return h.toFixed(2)+' h';return Math.round(sec/60)+' min'}
  function dashboardData422(){
    const algs=state.algorithms||[],jobs=state.jobs||[],dss=state.datasets||[],blue=state.v42?.blueprints||[];
    const versions=algs.reduce((n,a)=>n+(a.versions||[]).length,0),trained=algs.filter(a=>(a.versions||[]).length>0).length;
    const running=jobs.filter(j=>j.status==='running').length,queued=jobs.filter(j=>j.status==='queued').length,doneJobs=jobs.filter(j=>['done','finished','completed'].includes(j.status)),failed=jobs.filter(j=>j.status==='failed').length;
    const totalSeconds=jobs.reduce((n,j)=>n+jobDuration422(j),0),avgSeconds=doneJobs.length?doneJobs.reduce((n,j)=>n+jobDuration422(j),0)/doneJobs.length:0,successRate=(doneJobs.length+failed)?doneJobs.length/(doneJobs.length+failed):0;
    const totalImages=dss.reduce((n,d)=>n+Number(d.images||0),0),annotated=dss.reduce((n,d)=>n+Number(d.annotated_images||0),0),boxes=dss.reduce((n,d)=>n+Number(d.boxes||0),0);
    const dsKinds={全标注:0,混合:0,未标注:0,空数据集:0};dss.forEach(d=>{const im=Number(d.images||0),an=Number(d.annotated_images||0);if(!im)dsKinds['空数据集']++;else if(an===im)dsKinds['全标注']++;else if(an>0)dsKinds['混合']++;else dsKinds['未标注']++});
    const measured=(state.v42?.quality?.algorithms||[]).map(a=>a.metrics||{}).filter(m=>m.map50!=null||m.precision!=null||m.recall!=null);const mean=k=>{const vals=measured.map(m=>Number(m[k])).filter(Number.isFinite);return vals.length?vals.reduce((a,b)=>a+b,0)/vals.length:null};const maps=measured.map(m=>Number(m.map50)).filter(Number.isFinite);
    const ready=(state.targets||[]).filter(x=>x.status==='ready').length;const days=[];for(let i=6;i>=0;i--){const d=new Date();d.setHours(0,0,0,0);d.setDate(d.getDate()-i);const key=d.toISOString().slice(0,10);const rows=jobs.filter(j=>String(j.created_at||'').slice(0,10)===key);days.push({label:(d.getMonth()+1)+'/'+d.getDate(),count:rows.length})}
    return {algs,jobs,dss,versions,trained,running,queued,done:doneJobs.length,failed,totalSeconds,avgSeconds,successRate,totalImages,annotated,boxes,dsKinds,meanP:mean('precision'),meanR:mean('recall'),meanM:mean('map50'),bestMap:maps.length?Math.max(...maps):null,measured:measured.length,ready,days};
  }

  // -------- Dashboard --------
  function renderDashboard422(){
    const d=dashboardData422(); const max=Math.max(1,...d.days.map(x=>x.count));
    const sourceCount=(state.v42?.sources||[]).length, autoSource=(state.v42?.sources||[]).filter(x=>x.collect_mode==='auto').length;
    const pre=state.prelabelTasks||[], preRun=pre.filter(x=>['queued','running'].includes(x.status)).length;
    const latest=d.jobs.slice(0,5).map(j=>`<tr><td><b>${esc(j.run_name||j.algorithm_name||j.name||j.id)}</b></td><td>${status423(j.status)}</td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td>${fmtHours422(jobDuration422(j))}</td><td>${j.progress_percent!=null?Math.round(j.progress_percent)+'%':'-'}</td></tr>`).join('')||'<tr><td colspan="5" class="empty-row">暂无训练记录</td></tr>';
    const dsTotal=Math.max(1,d.dss.length); const dsBars=Object.entries(d.dsKinds).map(([k,v])=>`<div class="ops422-seg-row"><span>${k}</span><i><b style="width:${v/dsTotal*100}%"></b></i><strong>${v}</strong></div>`).join('');
    document.getElementById('view').innerHTML=`<div class="ops422">
      <section class="ops422-head"><div><span class="ops422-eyebrow">ALGORITHM OPERATIONS</span><h2>算法生产总览</h2></div><div class="row"><button class="btn" onclick="setPage('素材接入')">素材接入</button><button class="btn primary" onclick="openNewAlgorithm422()">新建算法</button></div></section>
      <section class="ops422-kpi-grid">
        <div class="ops422-kpi accent"><span>算法总数</span><b>${fmt422(d.algs.length)}</b><small>${d.trained} 个已训练 · ${d.versions} 个版本</small></div>
        <div class="ops422-kpi"><span>正在训练</span><b>${d.running}</b><small>${d.queued} 个排队任务</small></div>
        <div class="ops422-kpi"><span>数据集</span><b>${fmt422(d.dss.length)}</b><small>${fmt422(d.totalImages)} 张素材</small></div>
        <div class="ops422-kpi"><span>训练总时长</span><b>${fmtHours422(d.totalSeconds)}</b><small>平均 ${fmtHours422(d.avgSeconds)}</small></div>
        <div class="ops422-kpi"><span>训练成功率</span><b>${(d.successRate*100).toFixed(1)}%</b><small>${d.done} 成功 · ${d.failed} 失败</small></div>
        <div class="ops422-kpi"><span>自动标注中</span><b>${preRun}</b><small>${sourceCount} 个素材源 · ${autoSource} 个自动</small></div>
      </section>
      <section class="ops422-main-grid">
        <div class="ops422-card ops422-trend"><div class="ops422-card-head"><b>近 7 天训练任务</b><span>${d.jobs.length} 条训练记录</span></div><div class="ops422-bars">${d.days.map(x=>`<div><b>${x.count}</b><i><span style="height:${Math.max(5,x.count/max*100)}%"></span></i><em>${x.label}</em></div>`).join('')}</div></div>
        <div class="ops422-card"><div class="ops422-card-head"><b>算法质量</b><span>${d.measured} 个算法有指标</span></div><div class="ops422-quality"><div><span>Precision</span><b>${pct423(d.meanP)}</b></div><div><span>Recall</span><b>${pct423(d.meanR)}</b></div><div><span>mAP50</span><b>${pct423(d.meanM)}</b></div><div><span>最高 mAP50</span><b>${pct423(d.bestMap)}</b></div></div></div>
        <div class="ops422-card"><div class="ops422-card-head"><b>数据集构成</b><span>标注率 ${d.totalImages?((d.annotated/d.totalImages)*100).toFixed(1):'0.0'}%</span></div><div class="ops422-segments">${dsBars}</div><div class="ops422-mini"><span>图片 <b>${fmt422(d.totalImages)}</b></span><span>已标注 <b>${fmt422(d.annotated)}</b></span><span>标注框 <b>${fmt422(d.boxes)}</b></span></div></div>
        <div class="ops422-card"><div class="ops422-card-head"><b>运行资源</b><span>${d.ready} 个可用训练资源</span></div><div class="ops422-resource"><div><span>可用训练资源</span><b>${d.ready}</b></div><div><span>训练中任务</span><b>${d.running}</b></div><div><span>素材源</span><b>${sourceCount}</b></div><div><span>自动标注中</span><b>${preRun}</b></div></div></div>
      </section>
      <section class="ops422-card ops422-recent"><div class="ops422-card-head"><b>最近训练</b><button class="btn mini" onclick="setPage('训练任务')">全部</button></div><div class="table-wrap"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>数据集</th><th>耗时</th><th>进度</th></tr></thead><tbody>${latest}</tbody></table></div></section>
    </div>`;
  }

  // -------- Algorithm list --------
  function algorithmRows422(){
    const q=(document.getElementById('alg422Q')?.value||'').trim().toLowerCase();
    const ind=document.getElementById('alg422Industry')?.value||'all'; const st=document.getElementById('alg422Status')?.value||'all';
    const bp=state.v42?.blueprints||[];
    return (state.algorithms||[]).map(a=>{const b=bp.find(x=>x.algorithm_id===a.id)||{},vers=a.versions||[],last=vers[0]||{},m={metrics:{precision:versionMetric422(a,'precision'),recall:versionMetric422(a,'recall'),map50:versionMetric422(a,'map50')}};return {a,b,m,industry:b.industry||'未分类',trained:vers.length>0,last}})
      .filter(x=>(!q||`${x.a.name} ${x.a.remark||''} ${x.industry} ${(x.b.labels||[]).join(' ')}`.toLowerCase().includes(q))&&(ind==='all'||x.industry===ind)&&(st==='all'||(st==='trained'?x.trained:!x.trained)));
  }
  // -------- Sources --------
  function sourceType422(t){return ({folder:'目录 / 共享目录',rtsp:'视频流 / RTSP',http_json:'业务系统 API'}[t]||t)}
  function sourceMode422(s){if(s.collect_mode==='auto')return s.schedule_type==='daily'?`自动 · 每天 ${esc(s.schedule_value||'02:00')}`:`自动 · 每 ${esc(s.schedule_value||'60')} 分钟`;return '手动'}
  function sourceRows422(){const f=state.source422Filters;return (state.v42?.sources||[]).filter(s=>{const status=s.runtime_status||s.status||'unchecked';return(!f.q||`${s.name} ${s.source}`.toLowerCase().includes(f.q.toLowerCase()))&&(f.type==='all'||s.type===f.type)&&(f.status==='all'||status===f.status)&&(f.mode==='all'||(s.collect_mode||'manual')===f.mode)})}
  function renderSourceRows422(){const box=document.getElementById('source422Rows');if(!box)return;const rows=sourceRows422();box.innerHTML=rows.map(s=>`<tr><td><div class="source422-name"><b>${esc(s.name)}</b><span>${esc(s.source)}</span></div></td><td>${sourceType422(s.type)}</td><td>${status423(s.runtime_status||s.status)}</td><td>${sourceMode422(s)}</td><td>${esc((state.datasets||[]).find(d=>d.id===(s.dataset_id||'default'))?.name||s.dataset_id||'默认数据集')}</td><td>${dt423(s.last_completed_at)}</td><td>${s.collect_mode==='auto'?dt423(s.next_run_at):'-'}</td><td>${fmt422(s.last_imported||0)}</td><td><div class="row"><button class="btn mini" onclick="testSource422('${s.id}')">检测</button><button class="btn mini primary" onclick="runSourceNow422('${s.id}')">立即采集</button><button class="btn mini" onclick="openSource422('${s.id}')">编辑</button><button class="btn mini ${s.enabled===false?'green':'soft'}" onclick="toggleSource422('${s.id}')">${s.enabled===false?'启用':'停用'}</button><button class="btn mini danger" onclick="deleteSource422('${s.id}')">删除</button></div></td></tr>`).join('')||'<tr><td colspan="9" class="empty-row">暂无素材源</td></tr>'}
  window.applySourceFilters422=function(){state.source422Filters={q:document.getElementById('src422Q')?.value||'',type:document.getElementById('src422Type')?.value||'all',status:document.getElementById('src422Status')?.value||'all',mode:document.getElementById('src422Mode')?.value||'all'};renderSourceRows422()};
  async function refreshSources422(){const r=await safe(api(`/api/v42/projects/${pid()}/sources`));state.v42.sources=r?.items||[];renderSourceRows422()}
  window.renderSources422=async function(){await loadSourcesOnly422();const s=state.v42.sources||[];document.getElementById('view').innerHTML=`<div class="source422"><div class="source422-top"><div class="source422-stats"><div><span>素材源</span><b>${s.length}</b></div><div><span>自动执行</span><b>${s.filter(x=>x.collect_mode==='auto').length}</b></div><div><span>运行中</span><b>${s.filter(x=>['queued','running'].includes(x.runtime_status)).length}</b></div><div><span>异常</span><b>${s.filter(x=>(x.runtime_status||x.status)==='failed').length}</b></div></div><button class="btn primary" onclick="openSource422()">＋ 新增素材源</button></div><section class="panel"><div class="source422-filterbar"><input id="src422Q" class="input" placeholder="搜索名称或地址" oninput="applySourceFilters422()"><select id="src422Type" class="select" onchange="applySourceFilters422()"><option value="all">全部接入方式</option><option value="folder">目录 / 共享目录</option><option value="rtsp">视频流 / RTSP</option><option value="http_json">业务系统 API</option></select><select id="src422Status" class="select" onchange="applySourceFilters422()"><option value="all">全部状态</option><option value="ready">正常</option><option value="queued">排队中</option><option value="running">运行中</option><option value="failed">失败</option><option value="unchecked">未检测</option><option value="disabled">已停用</option></select><select id="src422Mode" class="select" onchange="applySourceFilters422()"><option value="all">全部执行方式</option><option value="manual">手动</option><option value="auto">自动</option></select><button class="btn" onclick="refreshSources422()">刷新</button></div><div class="table-wrap"><table class="table source422-table"><thead><tr><th>素材源</th><th>接入方式</th><th>状态</th><th>执行方式</th><th>目标数据集</th><th>最近完成</th><th>下次执行</th><th>最近入库</th><th>操作</th></tr></thead><tbody id="source422Rows"></tbody></table></div></section></div>`;renderSourceRows422();window.PollRegistryRuntime?.replaceSourceTimer?.()};
  window.refreshSources422=refreshSources422;
  window.openSource422=async function(id=''){if(!(state.v42.sources||[]).length)await loadSourcesOnly422();const s=(state.v42.sources||[]).find(x=>x.id===id)||{type:'folder',collect_mode:'manual',schedule_type:'interval',schedule_value:'60',dataset_id:state.datasetId||'default',max_items:100,interval_seconds:2,enabled:true,headers_json:'{}',items_path:'items',image_url_field:'image_url'};modal(id?'编辑素材源':'新增素材源',`<div class="form two"><div class="field"><label>名称</label><input id="src422Name" class="input" value="${esc(s.name||'')}"></div><div class="field"><label>接入方式</label><select id="src422EditType" class="select" onchange="toggleSourceForm422()"><option value="folder" ${s.type==='folder'?'selected':''}>目录 / 共享目录</option><option value="rtsp" ${s.type==='rtsp'?'selected':''}>视频流 / RTSP</option><option value="http_json" ${s.type==='http_json'?'selected':''}>业务系统 API</option></select></div><div class="field full"><label>来源地址</label><input id="src422Address" class="input" value="${esc(s.source||'')}"></div><div class="field"><label>执行方式</label><select id="src422EditMode" class="select" onchange="toggleSourceForm422()"><option value="manual" ${s.collect_mode!=='auto'?'selected':''}>手动</option><option value="auto" ${s.collect_mode==='auto'?'selected':''}>自动</option></select></div><div class="field"><label>目标数据集</label><select id="src422Dataset" class="select">${(state.datasets||[]).map(d=>`<option value="${d.id}" ${d.id===(s.dataset_id||'default')?'selected':''}>${esc(d.name)}</option>`).join('')}</select></div><div id="src422ScheduleTypeWrap" class="field"><label>自动执行周期</label><select id="src422ScheduleType" class="select" onchange="toggleSourceForm422()"><option value="interval" ${s.schedule_type!=='daily'?'selected':''}>按间隔</option><option value="daily" ${s.schedule_type==='daily'?'selected':''}>每天定时</option></select></div><div id="src422ScheduleValueWrap" class="field"><label id="src422ScheduleLabel">间隔分钟</label><input id="src422ScheduleValue" class="input" value="${esc(s.schedule_value||'60')}"></div><div class="field"><label>单次最多采集</label><input id="src422Max" class="input" value="${Number(s.max_items||100)}"></div><div class="field"><label>视频抽帧间隔（秒）</label><input id="src422Interval" class="input" value="${Number(s.interval_seconds||2)}"></div><div id="src422HttpWrap" class="field full"><div class="form two"><div class="field full"><label>Headers JSON</label><textarea id="src422Headers">${esc(s.headers_json||'{}')}</textarea></div><div class="field"><label>列表路径</label><input id="src422Items" class="input" value="${esc(s.items_path||'items')}"></div><div class="field"><label>图片 URL 字段</label><input id="src422ImageField" class="input" value="${esc(s.image_url_field||'image_url')}"></div></div></div><div class="field check"><label><input id="src422Enabled" type="checkbox" ${s.enabled===false?'':'checked'}> 启用</label></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveSource422('${id}')">保存</button></div>`,true);toggleSourceForm422()};
  window.toggleSourceForm422=function(){const typ=document.getElementById('src422EditType')?.value,mode=document.getElementById('src422EditMode')?.value,sch=document.getElementById('src422ScheduleType')?.value;const h=document.getElementById('src422HttpWrap');if(h)h.style.display=typ==='http_json'?'block':'none';['src422ScheduleTypeWrap','src422ScheduleValueWrap'].forEach(id=>{const e=document.getElementById(id);if(e)e.style.display=mode==='auto'?'block':'none'});const l=document.getElementById('src422ScheduleLabel');if(l)l.textContent=sch==='daily'?'每天时间（HH:MM）':'间隔分钟'};
  window.saveSource422=async function(id=''){const body={name:document.getElementById('src422Name')?.value||'',type:document.getElementById('src422EditType')?.value||'folder',source:document.getElementById('src422Address')?.value||'',collect_mode:document.getElementById('src422EditMode')?.value||'manual',schedule_type:document.getElementById('src422ScheduleType')?.value||'interval',schedule_value:document.getElementById('src422ScheduleValue')?.value||'60',dataset_id:document.getElementById('src422Dataset')?.value||'default',max_items:Number(document.getElementById('src422Max')?.value||100),interval_seconds:Number(document.getElementById('src422Interval')?.value||2),headers_json:document.getElementById('src422Headers')?.value||'{}',items_path:document.getElementById('src422Items')?.value||'items',image_url_field:document.getElementById('src422ImageField')?.value||'image_url',enabled:!!document.getElementById('src422Enabled')?.checked,remark:''};try{await api(`/api/v42/projects/${pid()}/sources${id?'/'+id:''}`,{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeModal();await loadSourcesOnly422();renderSources422();toast('素材源已保存')}catch(e){toast(e.message||e)}};
  window.testSource422=async id=>{try{const r=await api(`/api/v42/projects/${pid()}/sources/${id}/test`,{method:'POST'});toast(r.message||'检测成功')}catch(e){toast(e.message||e)}finally{await refreshSources422()}};
  window.runSourceNow422=async id=>{const s=(state.v42.sources||[]).find(x=>x.id===id);if(!s)return;try{await api(`/api/v42/projects/${pid()}/sources/${id}/collect`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset_id:s.dataset_id||'default',max_items:Number(s.max_items||100),interval_seconds:Number(s.interval_seconds||2)})});toast('采集任务已启动');await refreshSources422()}catch(e){toast(e.message||e)}};
  window.toggleSource422=async id=>{const s=(state.v42.sources||[]).find(x=>x.id===id);if(!s)return;const body={...s,enabled:s.enabled===false};['id','status','message','created_at','updated_at','last_run','last_completed_at','last_imported','next_run_at','runtime_status','last_checked_at'].forEach(k=>delete body[k]);try{await api(`/api/v42/projects/${pid()}/sources/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});await loadSourcesOnly422();renderSources422()}catch(e){toast(e.message||e)}};
  window.deleteSource422=async id=>{if(!confirm('确认删除这个素材源？已进入数据集的素材不会删除。'))return;await safe(api(`/api/v42/projects/${pid()}/sources/${id}`,{method:'DELETE'}));await loadSourcesOnly422();renderSources422()};

  // -------- Auto label --------
  function autoTaskRows422(){const f=state.auto422Filters;return (state.prelabelTasks||[]).filter(t=>{const model=t.model_name||'-',ds=t.dataset_id||'default';return(!f.q||`${t.name||''} ${t.target_label||''} ${model}`.toLowerCase().includes(f.q.toLowerCase()))&&(f.status==='all'||t.status===f.status)&&(f.model==='all'||model===f.model)&&(f.dataset==='all'||ds===f.dataset)})}
  function renderAutoRows422(){const box=document.getElementById('auto422Rows');if(!box)return;const rows=autoTaskRows422();box.innerHTML=rows.map(t=>`<tr><td><div class="source422-name"><b>${esc(t.name||t.id)}</b><span>${esc(t.id)}</span></div></td><td>${esc((state.datasets||[]).find(d=>d.id===(t.dataset_id||'default'))?.name||t.dataset_id||'默认数据集')}</td><td>${esc(t.model_name||'-')}${t.prompt_template_name?`<div class="muted-line">${esc(t.prompt_template_name)}</div>`:''}</td><td>${esc(t.target_label||'-')}</td><td>${status423(t.status)}</td><td><div class="task422-progress"><i><b style="width:${Number(t.progress||0)}%"></b></i><span>${t.processed_images||0}/${t.total_images||0} · ${t.boxes_added||0} 框</span></div></td><td>${dt423(t.started_at||t.created_at)}</td><td>${dt423(t.finished_at)}</td><td><div class="row"><button class="btn mini" onclick="autoTaskDetail422('${t.id}')">详情</button>${['queued','running'].includes(t.status)?`<button class="btn mini danger" onclick="stopAutoTask422('${t.id}')">停止</button>`:''}${['failed','stopped'].includes(t.status)?`<button class="btn mini primary" onclick="retryAutoTask422('${t.id}')">重试</button>`:''}</div></td></tr>`).join('')||'<tr><td colspan="9" class="empty-row">暂无自动标注任务</td></tr>'}
  window.applyAutoFilters422=function(){state.auto422Filters={q:document.getElementById('auto422Q')?.value||'',status:document.getElementById('auto422Status')?.value||'all',model:document.getElementById('auto422Model')?.value||'all',dataset:document.getElementById('auto422DatasetFilter')?.value||'all'};renderAutoRows422()};
  async function refreshAuto422(){state.prelabelTasks=(await safe(api(`/api/v33/projects/${pid()}/prelabel-tasks`)))?.items||[];renderAutoRows422()}
  window.renderAutoLabel422=async function(){await loadAll();const tasks=state.prelabelTasks||[],models=[...new Set(tasks.map(x=>x.model_name).filter(Boolean))];document.getElementById('view').innerHTML=`<div class="auto422"><div class="auto422-top"><div class="source422-stats"><div><span>任务总数</span><b>${tasks.length}</b></div><div><span>运行中</span><b>${tasks.filter(x=>['queued','running'].includes(x.status)).length}</b></div><div><span>已完成</span><b>${tasks.filter(x=>x.status==='done').length}</b></div><div><span>失败</span><b>${tasks.filter(x=>x.status==='failed').length}</b></div></div><div class="row"><button class="btn" onclick="setPage('模型配置')">模型配置</button><button class="btn primary" onclick="openAutoTask422()">＋ 新建自动标注任务</button></div></div><section class="panel"><div class="source422-filterbar"><input id="auto422Q" class="input" placeholder="搜索任务或标签" oninput="applyAutoFilters422()"><select id="auto422Status" class="select" onchange="applyAutoFilters422()"><option value="all">全部状态</option><option value="queued">排队中</option><option value="running">运行中</option><option value="done">已完成</option><option value="failed">失败</option><option value="stopped">已停止</option></select><select id="auto422Model" class="select" onchange="applyAutoFilters422()"><option value="all">全部模型</option>${models.map(x=>`<option>${esc(x)}</option>`).join('')}</select><select id="auto422DatasetFilter" class="select" onchange="applyAutoFilters422()"><option value="all">全部数据集</option>${(state.datasets||[]).map(d=>`<option value="${d.id}">${esc(d.name)}</option>`).join('')}</select><button class="btn" onclick="refreshAuto422()">刷新</button></div><div class="table-wrap"><table class="table auto422-table"><thead><tr><th>任务</th><th>数据集</th><th>模型 / 模板</th><th>标签</th><th>状态</th><th>进度</th><th>开始时间</th><th>完成时间</th><th>操作</th></tr></thead><tbody id="auto422Rows"></tbody></table></div></section></div>`;renderAutoRows422()};
  window.refreshAuto422=refreshAuto422;
  window.loadAutoDataset422=async function(){const ds=document.getElementById('at422Dataset')?.value||'default';state.auto422Images=await safe(api(`/api/projects/${pid()}/images?dataset_id=${ds}`))||[];const all=state.auto422Images.length,un=state.auto422Images.filter(x=>(x.box_count||0)===0).length,marked=all-un;const e=document.getElementById('at422Count');if(e)e.textContent=`${all} 张 · 未标注 ${un} · 已标注 ${marked}`};
  window.openAutoTask422=async function(){await loadAll();if(!(state.modelConfigs||[]).length)return modal('自动标注',`<div class="empty">暂无可用模型配置</div><div class="row end"><button class="btn primary" onclick="closeModal();setPage('模型配置')">去配置模型</button></div>`,true);modal('新建自动标注任务',`<div class="form two"><div class="field"><label>任务名称</label><input id="at422Name" class="input" value="自动标注-${new Date().toLocaleDateString('zh-CN')}"></div><div class="field"><label>数据集</label><select id="at422Dataset" class="select" onchange="loadAutoDataset422()">${(state.datasets||[]).map(d=>`<option value="${d.id}" ${d.id===state.datasetId?'selected':''}>${esc(d.name)}</option>`).join('')}</select><span id="at422Count" class="field-meta"></span></div><div class="field"><label>模型</label><select id="at422Model" class="select">${(state.modelConfigs||[]).map(m=>`<option value="${m.id}">${esc(m.name)}</option>`).join('')}</select></div><div class="field"><label>提示词模板</label><select id="at422Tpl" class="select" onchange="applyAutoTpl422()"><option value="">不使用模板</option>${(state.promptTemplates||[]).map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join('')}</select></div><div class="field"><label>标注范围</label><select id="at422Range" class="select"><option value="unmarked">仅未标注图片</option><option value="all">全部图片</option><option value="marked">仅已标注图片</option></select></div><div class="field"><label>目标标签</label><input id="at422Label" class="input" list="at422Labels" value="${esc((state.labels?.[0]?.code)||'person')}"><datalist id="at422Labels">${(state.labels||[]).map(x=>`<option value="${esc(x.code||x.display_name||x)}">`).join('')}</datalist></div><div class="field"><label>置信度阈值</label><input id="at422Threshold" class="input" value="0.5"></div><div class="field"><label>输出格式</label><select id="at422Format" class="select"><option value="internal">平台内部标注</option><option value="ultralytics">YOLO / Ultralytics</option><option value="paddle">COCO / Paddle</option></select></div><div class="field check"><label><input id="at422Overwrite" type="checkbox"> 覆盖同标签旧框</label></div></div><div class="row between"><button class="btn" onclick="testAutoModel422()">检测模型</button><div class="row"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="createAutoTask422()">创建任务</button></div></div>`,true);setTimeout(loadAutoDataset422,20)};
  window.applyAutoTpl422=function(){const t=(state.promptTemplates||[]).find(x=>x.id===document.getElementById('at422Tpl')?.value);if(!t)return;if(t.model_config_id)document.getElementById('at422Model').value=t.model_config_id;if((t.labels||[]).length)document.getElementById('at422Label').value=t.labels[0];if(t.threshold!=null)document.getElementById('at422Threshold').value=t.threshold;if(t.save_format)document.getElementById('at422Format').value=t.save_format==='yolo'?'ultralytics':t.save_format};
  window.testAutoModel422=async function(){const id=document.getElementById('at422Model')?.value;if(!id)return toast('请选择模型');try{const r=await api(`/api/v42/model-configs/${id}/test`,{method:'POST'});toast(`模型连接正常 · HTTP ${r.status_code}`)}catch(e){toast(e.message||e)}};
  window.createAutoTask422=async function(){const range=document.getElementById('at422Range')?.value||'unmarked',all=state.auto422Images||[];const imgs=range==='all'?all:range==='marked'?all.filter(x=>(x.box_count||0)>0):all.filter(x=>(x.box_count||0)===0);if(!imgs.length)return toast('当前范围没有可标注图片');const tpl=(state.promptTemplates||[]).find(x=>x.id===document.getElementById('at422Tpl')?.value);const body={model_config_id:document.getElementById('at422Model')?.value||null,prompt_template_id:tpl?.id||null,request_mode:'json_base64',image_field:'image',prompt:tpl?.prompt||'',threshold:Number(document.getElementById('at422Threshold')?.value||0.5),target_label:document.getElementById('at422Label')?.value||'person',image_ids:imgs.map(x=>x.id),overwrite:!!document.getElementById('at422Overwrite')?.checked,task_name:document.getElementById('at422Name')?.value||'自动标注任务',training_framework:document.getElementById('at422Format')?.value||'internal',dataset_id:document.getElementById('at422Dataset')?.value||'default',include_empty:false};try{await api(`/api/v35/projects/${pid()}/prelabel-tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeModal();await refreshAuto422();toast('自动标注任务已创建')}catch(e){toast(e.message||e)}};
  window.autoTaskDetail422=function(id){const t=(state.prelabelTasks||[]).find(x=>x.id===id);if(!t)return;modal('自动标注任务详情',`<div class="detail422-grid"><div><span>任务编号</span><b>${esc(t.id)}</b></div><div><span>状态</span><b>${status423(t.status)}</b></div><div><span>模型</span><b>${esc(t.model_name||'-')}</b></div><div><span>标签</span><b>${esc(t.target_label||'-')}</b></div><div><span>处理图片</span><b>${t.processed_images||0}/${t.total_images||0}</b></div><div><span>新增标注框</span><b>${t.boxes_added||0}</b></div><div><span>开始</span><b>${dt423(t.started_at||t.created_at)}</b></div><div><span>完成</span><b>${dt423(t.finished_at)}</b></div></div>${t.error?`<div class="error-box422">${esc(t.error)}</div>`:''}${(t.errors||[]).length?`<div class="error-list422">${t.errors.map(x=>`<div>${esc(x.image||'')} · ${esc(x.error||'')}</div>`).join('')}</div>`:''}`,true)};
  window.stopAutoTask422=async id=>{await safe(api(`/api/v33/projects/${pid()}/prelabel-tasks/${id}/stop`,{method:'POST'}));await refreshAuto422();toast('已请求停止')};
  window.retryAutoTask422=async id=>{try{await api(`/api/v42/projects/${pid()}/prelabel-tasks/${id}/retry`,{method:'POST'});await refreshAuto422();toast('任务已重新创建')}catch(e){toast(e.message||e)}};

  const render422Base=render;
  render=function(){
    if(state.page==='新建算法'||state.page==='自动迭代'){window.setPage?.('算法列表');return}
    if(state.page==='工作台'){renderNav();renderTop();renderSummary();renderDashboard422();if(!state.v42?.loaded)load42(true).then(()=>{if(state.page==='工作台')renderDashboard422()});return}
    if(state.page==='素材接入'){renderNav();renderTop();renderSummary();renderSources422();return}
    render422Base();
  };
})();

// ============================================================
// v42.3 — algorithm asset hierarchy + version deployments + training task first
// ============================================================
(function(){
  const V423='42.24.0';
  state.alg423Expanded=state.alg423Expanded||{};
  state.train423AlgorithmId=state.train423AlgorithmId||'';
  state.train423Edit=false;
  function dt423(v){return v?String(v).replace('T',' ').slice(0,19):'-'}
  function pct423(v){if(v==null||Number.isNaN(Number(v)))return '-';const n=Number(v);return (n>1?n:n*100).toFixed(1)+'%'}
  function status423(s){const names={queued:'排队中',running:'训练中',done:'已完成',finished:'已完成',completed:'已完成',failed:'失败',stopped:'已停止',ready:'正常',unchecked:'未检测'};const cls=['done','finished','completed','ready'].includes(s)?'ok':s==='failed'?'err':'warn';return `<span class=\"pill ${cls}\">${esc(names[s]||s||'-')}</span>`}
  async function loadBlueprints423(){state.v42=state.v42||{};const r=await safe(api(`/api/v42/projects/${pid()}/algorithm-blueprints`));state.v42.blueprints=r?.items||[];return state.v42.blueprints}

  const ALG_TYPES423=[
    {id:'yolo_ultralytics',name:'YOLO / Ultralytics',short:'YOLO',trainable:true,framework:'ultralytics'},
    {id:'paddle_detection',name:'PaddleDetection',short:'PaddleDetection',trainable:true,framework:'paddle'},
    {id:'opencv',name:'OpenCV 传统视觉',short:'OpenCV',trainable:false,framework:'opencv'},
    {id:'mmdetection',name:'MMDetection / OpenMMLab',short:'MMDetection',trainable:false,framework:'mmdetection'},
    {id:'custom_python',name:'自定义 Python / 其他',short:'自定义',trainable:false,framework:'custom'}
  ];
  function algType423(id){return ALG_TYPES423.find(x=>x.id===id)||null}
  function algorithmMeta423(a){
    const b=(state.v42?.blueprints||[]).find(x=>x.algorithm_id===a.id)||{};
    return {industry:(a.industry||b.industry||'').trim(),algorithm_type:(a.algorithm_type||b.algorithm_type||'').trim()};
  }
  function metricFromVersion423(v,key){
    const rep=v?.report||{};for(const [k,val] of Object.entries(rep)){const low=String(k).toLowerCase().replace(/\s+/g,'');let hit=false;if(key==='precision')hit=low.includes('precision');if(key==='recall')hit=low.includes('recall');if(key==='map50')hit=low.includes('map50')&&!low.includes('95');if(hit){const n=Number(val);if(Number.isFinite(n))return n}}
    return null;
  }
  function algTypeOptions423(selected=''){return ALG_TYPES423.map(x=>`<option value="${x.id}" ${selected===x.id?'selected':''}>${x.name}</option>`).join('')}
  function industryOptions423(){const vals=[...(state.algorithms||[]).map(a=>a.industry).filter(Boolean),...(state.v42?.templates||[]).map(x=>x.industry).filter(Boolean)];return [...new Set(vals)].sort().map(x=>`<option value="${esc(x)}">`).join('')}
  function versionRows423(a,forModal=false){
    const vers=a.versions||[];
    const versionHtml=vers.length?`<div class="alg423-version-list">${vers.map(v=>{
      const p=metricFromVersion423(v,'precision'),r=metricFromVersion423(v,'recall'),m=metricFromVersion423(v,'map50');
      return `<div class="alg423-version" onclick="showVersionDeployments423('${a.id}','${v.id}')"><div class="alg423-ver-main"><div class="alg423-ver-name"><b>${esc(v.version_name||('V'+(v.version_no||'')))}</b><span>${esc(v.model_name||'')}</span></div><div class="alg423-ver-meta"><span>${esc(v.type||'模型')}</span><span>${Number(v.size_mb||0).toFixed(2)} MB</span><span>${dt423(v.created_at)}</span>${v.job_id?`<span>训练任务 ${esc(v.job_id)}</span>`:''}</div></div><div class="alg423-ver-metrics"><span>P <b>${pct423(p)}</b></span><span>R <b>${pct423(r)}</b></span><span>mAP50 <b>${pct423(m)}</b></span></div><div class="alg423-ver-actions"><button class="btn mini" onclick="event.stopPropagation();showReport('${a.id}','${v.id}')">训练报告</button><button class="btn mini primary" onclick="event.stopPropagation();showVersionDeployments423('${a.id}','${v.id}')">部署产物</button><a class="btn mini" onclick="event.stopPropagation()" href="/api/v12/projects/${pid()}/algorithms/${a.id}/versions/${v.id}/download">下载模型</a>${forModal?`<button class="btn mini danger" onclick="event.stopPropagation();delVersion('${a.id}','${v.id}')">删除版本</button>`:''}</div></div>`;
    }).join('')}</div>`:'<div class="alg423-nover">暂无正式版本</div>';
    const jobs=(state.jobs||[]).filter(j=>j.asset_algorithm_id===a.id).slice(0,5);
    const jobHtml=jobs.length?`<div class="alg424-train-results"><div class="alg423-detail-title"><b>关联训练成果</b><span>${jobs.length} 条</span></div>${jobs.map(j=>{const arts=[j.best_model,j.last_model].filter(Boolean);return `<div class="alg424-train-result"><div><b>${esc(j.id)}</b><span>${esc(j.framework||'')} · ${esc(j.model||'')}</span><em>${esc(j.status_text||j.status||'')}</em></div><div class="alg424-train-files">${arts.map(x=>`<span>${esc(String(x).split(/[\\/]/).pop())}</span>`).join('')||'<span>暂无模型产物</span>'}</div><div class="row"><button class="btn mini" onclick="event.stopPropagation();showTrainLog424('${j.id}')">训练日志</button><button class="btn mini" onclick="event.stopPropagation();showTrainReport424('${j.id}')">训练报告</button></div></div>`}).join('')}</div>`:'';
    return versionHtml+jobHtml;
  }
  function filteredAlgorithms423(){
    const q=(document.getElementById('alg423Q')?.value||'').trim().toLowerCase();
    const type=document.getElementById('alg423Type')?.value||'all';
    const industry=document.getElementById('alg423Industry')?.value||'all';
    return (state.algorithms||[]).filter(a=>{const m=algorithmMeta423(a);return(!q||`${a.name} ${a.remark||''} ${m.industry} ${m.algorithm_type}`.toLowerCase().includes(q))&&(type==='all'||m.algorithm_type===type)&&(industry==='all'||m.industry===industry)});
  }
  function renderAlgorithmList423(){
    const box=document.getElementById('alg423List');if(!box)return;
    const rows=filteredAlgorithms423();
    box.innerHTML=rows.map(a=>{const m=algorithmMeta423(a),tp=algType423(m.algorithm_type),vers=a.versions||[],latest=vers[0]||null,expanded=!!state.alg423Expanded[a.id];return `<article class="alg423-card ${expanded?'expanded':''}" onclick="toggleAlgorithm423('${a.id}')"><div class="alg423-card-main"><div class="alg423-symbol">${esc((a.name||'算').slice(0,1))}</div><div class="alg423-info"><div class="alg423-title"><b>${esc(a.name)}</b>${tp?`<span class="alg423-type">${esc(tp.short)}</span>`:''}${m.industry?`<span class="alg423-industry">${esc(m.industry)}</span>`:''}</div><div class="alg423-desc">${esc(a.remark||'')}</div><div class="alg423-meta"><span>版本 ${vers.length}</span>${latest?`<span>最新 ${esc(latest.version_name||('V'+latest.version_no))}</span><span>${dt423(latest.created_at)}</span>`:''}</div></div><div class="alg423-stats"><div><span>Precision</span><b>${pct423(metricFromVersion423(latest,'precision'))}</b></div><div><span>Recall</span><b>${pct423(metricFromVersion423(latest,'recall'))}</b></div><div><span>mAP50</span><b>${pct423(metricFromVersion423(latest,'map50'))}</b></div></div><div class="alg423-actions"><button class="btn mini" onclick="event.stopPropagation();viewAlgorithm423('${a.id}')">详情</button><button class="btn mini" onclick="event.stopPropagation();editAlgorithm423('${a.id}')">编辑</button><button class="btn mini primary" onclick="event.stopPropagation();startAlgorithmTraining423('${a.id}')">训练</button><button class="btn mini danger" onclick="event.stopPropagation();delAlgorithm('${a.id}')">删除</button><span class="alg423-chevron">⌄</span></div></div><div class="alg423-expand" onclick="event.stopPropagation()">${expanded?versionRows423(a,false):''}</div></article>`}).join('')||'<div class="empty">暂无算法</div>';
  }
  window.toggleAlgorithm423=function(id){state.alg423Expanded[id]=!state.alg423Expanded[id];renderAlgorithmList423()};
  window.filterAlgorithms423=renderAlgorithmList423;
  window.renderAlgorithms423=async function(){
    await loadBlueprints423();
    const inds=[...new Set((state.algorithms||[]).map(a=>algorithmMeta423(a).industry).filter(Boolean))].sort();
    document.getElementById('view').innerHTML=`<section class="alg423-shell"><div class="alg423-toolbar"><div class="filter423"><input id="alg423Q" class="input" placeholder="搜索算法" oninput="filterAlgorithms423()"><select id="alg423Industry" class="select" onchange="filterAlgorithms423()"><option value="all">全部行业场景</option>${inds.map(x=>`<option>${esc(x)}</option>`).join('')}</select><select id="alg423Type" class="select" onchange="filterAlgorithms423()"><option value="all">全部算法类型</option>${algTypeOptions423()}</select></div><button class="btn primary" onclick="openNewAlgorithm423()">＋ 新建算法</button></div><div id="alg423List" class="alg423-list"></div></section>`;
    renderAlgorithmList423();
  };
  window.openNewAlgorithm423=async function(){
    if(!(state.v42?.templates||[]).length){const r=await safe(api('/api/v42/industry-templates'));state.v42=state.v42||{};state.v42.templates=r?.items||[];}
    modal('新建算法',`<div class="form two alg423-form"><div class="field"><label>算法名称</label><input id="a423Name" class="input"></div><div class="field"><label>行业场景</label><input id="a423Industry" class="input" list="a423IndustryList"><datalist id="a423IndustryList">${industryOptions423()}</datalist></div><div class="field full"><label>算法类型</label><select id="a423Type" class="select">${algTypeOptions423('yolo_ultralytics')}</select></div><div class="field full"><label>备注</label><textarea id="a423Remark"></textarea></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveNewAlgorithm423()">创建</button></div>`,true);
  };
  window.saveNewAlgorithm423=async function(){
    const name=document.getElementById('a423Name')?.value.trim();if(!name)return toast('请输入算法名称');
    const body={name,industry:document.getElementById('a423Industry')?.value.trim()||'',algorithm_type:document.getElementById('a423Type')?.value||'yolo_ultralytics',template_id:'custom',labels:[],focus_scenes:'',negative_scenes:'',remark:document.getElementById('a423Remark')?.value||''};
    try{await api(`/api/v42/projects/${pid()}/algorithm-blueprints`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeModal();await loadRelated();await renderAlgorithms423();toast('算法已创建')}catch(e){toast(e.message||e)}
  };
  window.editAlgorithm423=function(id){const a=(state.algorithms||[]).find(x=>x.id===id);if(!a)return;const m=algorithmMeta423(a);modal('编辑算法',`<div class="form two alg423-form"><div class="field"><label>算法名称</label><input id="ae423Name" class="input" value="${esc(a.name)}"></div><div class="field"><label>行业场景</label><input id="ae423Industry" class="input" value="${esc(m.industry)}" list="ae423IndustryList"><datalist id="ae423IndustryList">${industryOptions423()}</datalist></div><div class="field full"><label>算法类型</label><select id="ae423Type" class="select">${algTypeOptions423(m.algorithm_type)}</select></div><div class="field full"><label>备注</label><textarea id="ae423Remark">${esc(a.remark||'')}</textarea></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveEditAlgorithm423('${id}')">保存</button></div>`,true)};
  window.saveEditAlgorithm423=async function(id){try{await api(`/api/v12/projects/${pid()}/algorithms/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:document.getElementById('ae423Name')?.value||'',industry:document.getElementById('ae423Industry')?.value||'',algorithm_type:document.getElementById('ae423Type')?.value||'',remark:document.getElementById('ae423Remark')?.value||''})});closeModal();await loadRelated();await renderAlgorithms423();toast('已保存')}catch(e){toast(e.message||e)}};
  window.viewAlgorithm423=function(id){const a=(state.algorithms||[]).find(x=>x.id===id);if(!a)return;const m=algorithmMeta423(a),tp=algType423(m.algorithm_type);modal('算法详情',`<div class="alg423-detail-head"><div class="alg423-symbol big">${esc((a.name||'算').slice(0,1))}</div><div><h3>${esc(a.name)}</h3><div class="alg423-detail-tags">${tp?`<span>${esc(tp.name)}</span>`:''}${m.industry?`<span>${esc(m.industry)}</span>`:''}</div><p>${esc(a.remark||'')}</p></div></div><div class="alg423-detail-title"><b>算法版本</b><span>${(a.versions||[]).length} 个</span></div>${versionRows423(a,true)}`,true)};
  window.showVersionDeployments423=async function(aid,vid){
    try{const r=await api(`/api/v42/projects/${pid()}/algorithms/${aid}/versions/${vid}/deployments`);const v=r.version||{},items=r.items||[];modal(`${r.algorithm?.name||'算法'} · ${v.version_name||'版本'} · 部署产物`,`<div class="deploy423-source"><span>源模型</span><b>${esc(v.model_name||'')}</b><em>${Number(v.size_mb||0).toFixed(2)} MB</em></div><div class="deploy423-list">${items.map(j=>`<div class="deploy423-job"><div class="deploy423-job-head"><div><b>${esc(j.target_name||j.target)}</b><span>${status423(j.status)}</span></div><time>${dt423(j.finished_at||j.created_at)}</time></div><div class="deploy423-job-meta"><span>转换资源：${esc(j.resource_name||'-')}</span><span>任务：${esc(j.id)}</span>${j.params?.precision?`<span>精度：${esc(j.params.precision)}</span>`:''}${j.params?.input_size?`<span>输入：${esc(j.params.input_size)}</span>`:''}</div>${j.message?`<div class="deploy423-message">${esc(j.message)}</div>`:''}<div class="deploy423-files">${(j.outputs||[]).map(o=>`<div><span>${esc(o.name)}</span><b>${o.size_mb!=null?Number(o.size_mb).toFixed(2)+' MB':''}</b>${o.download_url?`<a class="btn mini" href="${o.download_url}">下载</a>`:''}</div>`).join('')||'<div class="empty-row">暂无输出文件</div>'}</div></div>`).join('')||'<div class="alg423-nover">该版本暂无部署转换产物</div>'}</div><div class="row end"><button class="btn primary" onclick="closeModal();setPage('部署转换')">创建部署转换</button></div>`,true)}catch(e){toast(e.message||e)}
  };

  // ---------- Training task page ----------
  function trainTaskRows423(){return (state.jobs||[]).map(j=>`<tr><td><div class="train423-name"><b>${esc(j.asset_algorithm_name||j.algorithm_name||j.run_name||j.id)}</b><span>${esc(j.id)}</span></div></td><td>${esc(j.framework==='paddle'?'PaddleDetection':'Ultralytics / YOLO')}</td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td>${status423(j.status)}</td><td>${renderJobProgress(j)}</td><td>${dt423(j.created_at)}</td><td><div class="row"><button class="btn mini" onclick="openTrainDetail423('${j.id}')">详情</button><button class="btn mini" onclick="showTrainLog423('${j.id}')">日志</button>${['queued','running','waiting','pending'].includes(j.status)?`<button class="btn mini danger" onclick="stopJob423('${j.id}')">停止</button>`:''}<button class="btn mini danger" onclick="deleteJob423('${j.id}')">删除</button></div></td></tr>`).join('')||'<tr><td colspan="7" class="empty-row">暂无训练任务</td></tr>'}
  window.renderTraining423=function(){document.getElementById('view').innerHTML=`<section class="train423-shell"><div class="train423-top"><div class="train423-stats"><div><span>任务总数</span><b>${(state.jobs||[]).length}</b></div><div><span>训练中</span><b>${(state.jobs||[]).filter(x=>x.status==='running').length}</b></div><div><span>排队中</span><b>${(state.jobs||[]).filter(x=>x.status==='queued').length}</b></div><div><span>已完成</span><b>${(state.jobs||[]).filter(x=>['done','finished','completed'].includes(x.status)).length}</b></div></div><button class="btn primary" onclick="openTrainTask423()">▶ 开始训练</button></div><section class="panel"><div class="source422-filterbar"><input id="train423Q" class="input" placeholder="搜索任务" oninput="filterTrain423()"><select id="train423Status" class="select" onchange="filterTrain423()"><option value="all">全部状态</option><option value="queued">排队中</option><option value="running">训练中</option><option value="done">已完成</option><option value="failed">失败</option><option value="stopped">已停止</option></select><button class="btn" onclick="refreshTrain423()">刷新</button></div><div class="table-wrap"><table class="table train423-table"><thead><tr><th>训练任务</th><th>训练框架</th><th>数据集</th><th>状态</th><th>进度 / 耗时</th><th>创建时间</th><th>操作</th></tr></thead><tbody id="train423Rows">${trainTaskRows423()}</tbody></table></div></section></section>`};
  window.filterTrain423=function(){const q=(document.getElementById('train423Q')?.value||'').toLowerCase(),s=document.getElementById('train423Status')?.value||'all';const rows=(state.jobs||[]).filter(j=>(!q||`${j.asset_algorithm_name||''} ${j.algorithm_name||''} ${j.id}`.toLowerCase().includes(q))&&(s==='all'||j.status===s));document.getElementById('train423Rows').innerHTML=rows.map(j=>`<tr><td><div class="train423-name"><b>${esc(j.asset_algorithm_name||j.algorithm_name||j.run_name||j.id)}</b><span>${esc(j.id)}</span></div></td><td>${esc(j.framework==='paddle'?'PaddleDetection':'Ultralytics / YOLO')}</td><td>${esc(j.dataset_name||j.dataset_id||'-')}</td><td>${status423(j.status)}</td><td>${renderJobProgress(j)}</td><td>${dt423(j.created_at)}</td><td><div class="row"><button class="btn mini" onclick="openTrainDetail423('${j.id}')">详情</button><button class="btn mini" onclick="showTrainLog423('${j.id}')">日志</button>${['queued','running','waiting','pending'].includes(j.status)?`<button class="btn mini danger" onclick="stopJob423('${j.id}')">停止</button>`:''}<button class="btn mini danger" onclick="deleteJob423('${j.id}')">删除</button></div></td></tr>`).join('')||'<tr><td colspan="7" class="empty-row">暂无训练任务</td></tr>'};
  window.refreshTrain423=async function(){const rows=await safe(api(`/api/projects/${pid()}/jobs`));if(Array.isArray(rows))state.jobs=rows;filterTrain423();toast('已刷新')};
  function eligibleTargets423(type){const tp=algType423(type);if(!tp||!tp.trainable)return[];return (state.targets||[]).filter(t=>t.status==='ready'&&(tp.framework==='paddle'?t.framework==='paddle':t.framework==='ultralytics'))}
  function selectedAsset423(){return (state.algorithms||[]).find(x=>x.id===document.getElementById('train423Asset')?.value)}
  window.openTrainTask423=async function(preselect=''){
    await loadAll();const selected=preselect||state.train423AlgorithmId||state.algorithms?.[0]?.id||'';state.train423AlgorithmId='';
    modal('创建训练任务',`<div class="train423-create"><div class="form two"><div class="field"><label>算法</label><select id="train423Asset" class="select" onchange="trainAssetChanged423()">${(state.algorithms||[]).map(a=>`<option value="${a.id}" ${a.id===selected?'selected':''}>${esc(a.name)}</option>`).join('')}</select></div><div class="field"><label>训练数据集</label><select id="trainDataset" class="select">${(state.datasets||[]).map(d=>`<option value="${d.id}" ${d.id===state.datasetId?'selected':''}>${esc(d.name)} · ${d.images||0} 图</option>`).join('')}</select></div><div class="field full"><label>训练资源</label><select id="target" class="select" onchange="trainTargetChanged423()"></select><div id="train423Unsupported" class="train423-unsupported hidden"></div></div></div><div class="train423-config"><div class="train423-config-head"><div><b>默认训练配置</b><span id="train423ConfigState">已锁定</span></div><button id="train423EditBtn" class="btn small" onclick="toggleTrainConfig423()">编辑训练配置</button></div><div class="form two"><div class="field"><label>训练算法</label><select class="select train423-lock" id="alg" onchange="applyAlg();syncTrainConfigSummary423()"></select><div id="algMeta" class="field-meta"></div></div><div class="field"><label>基础模型</label><select class="select train423-lock" id="model" onchange="syncTrainConfigSummary423()"></select><div id="modelMeta" class="field-meta"></div></div><div class="field"><label>训练轮次</label><input class="input train423-lock" id="epochs" value="100"></div><div class="field"><label>图片尺寸</label><input class="input train423-lock" id="imgsz" value="640"></div><div class="field"><label>批大小</label><input class="input train423-lock" id="batch" value="8"></div><div class="field"><label>训练设备</label><input class="input train423-lock" id="device" value="cpu"></div></div><details class="train423-advanced"><summary>高级配置</summary><div class="form two"><div class="field"><label>优化器</label><select class="select train423-lock" id="optimizer"><option value="auto">auto</option><option>SGD</option><option>Adam</option><option>AdamW</option><option>NAdam</option><option>RAdam</option><option>RMSProp</option></select></div><div class="field"><label>早停轮数</label><input class="input train423-lock" id="patience" value="100"></div><div class="field"><label>数据加载进程</label><input class="input train423-lock" id="workers" value="0"></div><div class="field"><label>初始学习率</label><input class="input train423-lock" id="lr0" value="0.01"></div><div class="field"><label>最终学习率比例</label><input class="input train423-lock" id="lrf" value="0.01"></div><div class="field"><label>权重衰减</label><input class="input train423-lock" id="weight_decay" value="0.0005"></div><div class="field"><label>关闭 Mosaic 轮数</label><input class="input train423-lock" id="close_mosaic" value="10"></div><div class="field"><label>Mosaic 强度</label><input class="input train423-lock" id="mosaic" value="1.0"></div><div class="field"><label>缓存</label><select class="select train423-lock" id="cache"><option value="False">关闭</option><option value="ram">内存缓存</option><option value="disk">磁盘缓存</option></select></div><div class="field"><label>冻结前 N 层</label><input class="input train423-lock" id="freeze" value="0"></div><div class="field check"><label><input class="train423-lock" type="checkbox" id="pretrained" checked> 加载预训练权重</label></div><div class="field check"><label><input class="train423-lock" type="checkbox" id="amp" checked> AMP 混合精度</label></div><div class="field check"><label><input class="train423-lock" type="checkbox" id="rect"> 矩形训练</label></div><div class="field check"><label><input class="train423-lock" type="checkbox" id="cos_lr"> 余弦学习率</label></div><div class="field check"><label><input class="train423-lock" type="checkbox" id="single_cls"> 单类别训练</label></div><div class="field check"><label><input class="train423-lock" type="checkbox" id="paddle_eval"> 飞桨训练中评估</label></div></div></details></div><div class="row between train423-submit"><div id="train423Summary" class="train423-summary"></div><div class="row"><button class="btn" onclick="closeModal()">取消</button><button id="train423Start" class="btn primary" onclick="startTrain423()">开始训练</button></div></div></div>`,true);
    setTimeout(()=>{trainAssetChanged423();state.train423Edit=false;lockTrain423(true)},20)
  };
  window.trainAssetChanged423=function(){const a=selectedAsset423(),m=a?algorithmMeta423(a):{},tp=algType423(m.algorithm_type),targets=eligibleTargets423(m.algorithm_type);const sel=document.getElementById('target'),warn=document.getElementById('train423Unsupported'),start=document.getElementById('train423Start');if(sel)sel.innerHTML=targets.map(t=>`<option value="${t.id}">${esc(t.name)} · ${t.framework==='paddle'?'PaddleDetection':'Ultralytics'}</option>`).join('');if(!targets.length){warn.classList.remove('hidden');warn.textContent=tp?.id==='opencv'?'OpenCV 传统视觉算法当前不走 YOLO/Paddle 深度学习训练任务。':tp?.id==='mmdetection'?'当前未接入 MMDetection 训练执行环境。':'当前算法类型没有可用训练执行环境。';if(start)start.disabled=true}else{warn.classList.add('hidden');if(start)start.disabled=false;trainTargetChanged423()}syncTrainConfigSummary423()};
  window.trainTargetChanged423=function(){if(typeof fillTrain==='function')fillTrain();const rec=state.rec?.recommendation||{};if(document.getElementById('epochs')&&!document.getElementById('epochs').value)document.getElementById('epochs').value=rec.epochs||100;if(document.getElementById('imgsz')&&!document.getElementById('imgsz').value)document.getElementById('imgsz').value=rec.imgsz||640;if(document.getElementById('batch')&&!document.getElementById('batch').value)document.getElementById('batch').value=rec.batch||8;if(document.getElementById('device')&&!document.getElementById('device').value)document.getElementById('device').value=rec.device||'cpu';const t=curTarget();const pe=document.getElementById('paddle_eval');if(pe)pe.disabled=!(t&&t.framework==='paddle')||!state.train423Edit;lockTrain423(!state.train423Edit);syncTrainConfigSummary423()};
  function lockTrain423(locked){document.querySelectorAll('.train423-lock').forEach(el=>{el.disabled=locked});const st=document.getElementById('train423ConfigState'),b=document.getElementById('train423EditBtn');if(st)st.textContent=locked?'已锁定':'可编辑';if(b)b.textContent=locked?'编辑训练配置':'恢复默认锁定';state.train423Edit=!locked}
  window.toggleTrainConfig423=function(){lockTrain423(state.train423Edit);syncTrainConfigSummary423()};
  window.syncTrainConfigSummary423=function(){const a=selectedAsset423(),t=curTarget();const el=document.getElementById('train423Summary');if(!el)return;el.innerHTML=`<span>${esc(a?.name||'-')}</span><span>${esc(t?.framework==='paddle'?'PaddleDetection':'Ultralytics / YOLO')}</span><span>${esc(document.getElementById('model')?.selectedOptions?.[0]?.textContent||document.getElementById('model')?.value||'-')}</span><span>${esc(document.getElementById('epochs')?.value||'-')} 轮</span>`};
    window.startAlgorithmTraining423=function(id){state.train423AlgorithmId=id;setPage('训练任务');setTimeout(()=>openTrainTask423(id),40)};
  window.openTrainDetail423=function(id){const j=(state.jobs||[]).find(x=>x.id===id);if(!j)return;modal('训练任务详情',`<div class="detail422-grid"><div><span>任务编号</span><b>${esc(j.id)}</b></div><div><span>算法</span><b>${esc(j.asset_algorithm_name||j.algorithm_name||'-')}</b></div><div><span>训练框架</span><b>${esc(j.framework==='paddle'?'PaddleDetection':'Ultralytics / YOLO')}</b></div><div><span>基础模型</span><b>${esc(j.model||'-')}</b></div><div><span>数据集</span><b>${esc(j.dataset_name||j.dataset_id||'-')}</b></div><div><span>状态</span><b>${status423(j.status)}</b></div><div><span>训练轮次</span><b>${esc(j.epochs||'-')}</b></div><div><span>图片尺寸</span><b>${esc(j.imgsz||'-')}</b></div><div><span>批大小</span><b>${esc(j.batch||'-')}</b></div><div><span>设备</span><b>${esc(j.device||'-')}</b></div><div><span>创建时间</span><b>${dt423(j.created_at)}</b></div><div><span>完成时间</span><b>${dt423(j.finished_at)}</b></div></div>${j.message?`<div class="deploy423-message">${esc(j.message)}</div>`:''}`,true)};
  window.showTrainLog423=async function(id){const txt=await safe(api(`/api/projects/${pid()}/jobs/${id}/log`));modal('训练日志',`<pre id="train423Log" class="log train423-log">${esc(txt||'暂无日志')}</pre><div class="row end"><button class="btn" onclick="refreshTrainLog423('${id}')">刷新</button><button class="btn" onclick="closeModal()">关闭</button></div>`,true)};
  window.refreshTrainLog423=async id=>{const txt=await safe(api(`/api/projects/${pid()}/jobs/${id}/log`));const el=document.getElementById('train423Log');if(el){el.textContent=txt||'暂无日志';el.scrollTop=el.scrollHeight}};
  window.stopJob423=async id=>{await safe(api(`/api/projects/${pid()}/jobs/${id}/stop`,{method:'POST'}));await refreshTrain423();toast('已请求停止')};
  window.deleteJob423=async id=>{if(!confirm('确认删除训练任务？'))return;await safe(api(`/api/v12/projects/${pid()}/jobs/${id}`,{method:'DELETE'}));await refreshTrain423();toast('已删除')};

  // Algorithm/training routing is owned by the later stable render layers.
})();

// ============================================================
// v42.4 — single data pool + quality center + usable task flows
// ============================================================
(function(){
  const V424='42.24.0';
  state.data424Tab=state.data424Tab||'unassigned';
  state.data424Label=state.data424Label||'all';
  state.data424Selected=state.data424Selected||new Set();
  state.train424Expanded=state.train424Expanded||{};
  state.train424Config=state.train424Config||null;
  state.train424Selected=state.train424Selected||{train:new Set(),val:new Set()};
  state.quality424=null;
  state.video424=[]; state.prelabel424=[];

  // ---------- modal stack: close always affects only top window ----------
  const baseModal=document.getElementById('modal');
  const dynamicModalStack=[];
  function makeLayer424(title,body,wide){
    const layer=document.createElement('div');
    layer.className='modal v424-modal-layer';
    const titleId=`v424ModalTitle${dynamicModalStack.length+1}`;
    layer.setAttribute('role','dialog');layer.setAttribute('aria-modal','true');layer.setAttribute('aria-labelledby',titleId);
    layer.style.zIndex=String(1100+dynamicModalStack.length*10);
    layer.innerHTML=`<div class="modal-card ${wide?'wide':''}"><div class="modal-head"><div id="${titleId}" class="modal-title">${esc(title||'')}</div><button class="icon" data-v424-close aria-label="关闭">×</button></div><div class="modal-body">${body||''}</div></div>`;
    layer.querySelector('[data-v424-close]').onclick=()=>closeModal();
    layer.addEventListener('mousedown',e=>{if(e.target===layer)closeModal()});
    document.body.appendChild(layer); dynamicModalStack.push(layer); return layer;
  }
  const oldModal424=modal, oldClose424=closeModal;
  modal=function(title,body,wide=false){
    if(baseModal && baseModal.classList.contains('hidden') && dynamicModalStack.length===0){
      oldModal424(title,body,wide); return baseModal;
    }
    return makeLayer424(title,body,wide);
  };
  window.modal=modal;
  closeModal=function(){
    if(dynamicModalStack.length){const top=dynamicModalStack.pop();top.remove();return}
    oldClose424();
  };
  window.closeModal=closeModal;
  window.closeAllModals424=function(){while(dynamicModalStack.length)dynamicModalStack.pop().remove();if(baseModal&&!baseModal.classList.contains('hidden'))oldClose424()};

  // ---------- all images are one logical data pool ----------
  const baseLoadRelated424=loadRelated;
  loadRelated=async function(){
    await baseLoadRelated424();
    if(state.project){state.images=await safe(api(`/api/projects/${pid()}/images`))||[];state.datasetId='default';}
  };

  function icon424(name){
    const map={'工作台':'▦','质量中心':'◇','算法列表':'◆','训练任务':'▶','数据集':'▤','视频切帧':'▣','自动标注':'✦','测试发布':'✓','检测台':'◎','部署转换':'⇄','部署产物':'▥','模型配置':'◉','训练资源':'▧','部署资源':'⬡'};
    return map[name]||'•';
  }
  const GROUPS424=[
    {title:'总览',items:['工作台','质量中心']},
    {title:'算法生产',items:['算法列表','训练任务']},
    {title:'数据中心',items:['数据集','视频切帧','自动标注']},
    {title:'测试评测',items:['测试发布','检测台']},
    {title:'部署中心',items:['部署转换','部署产物']},
    {title:'资源配置',items:['模型配置','训练资源','部署资源']},
  ];
  renderNav=function(){
    const projectName=esc(state.project?.name||'默认空间');
    document.getElementById('nav').innerHTML=`<div class="nav-project"><div class="nav-project-k">当前项目</div><div class="nav-project-v">${projectName}</div></div>${GROUPS424.map(g=>`<div class="nav-group"><div class="nav-group-title">${g.title}</div>${g.items.map(n=>`<button class="nav-btn ${state.page===n?'active':''}" onclick="setPage('${n}')"><span class="nav-left"><i>${icon424(n)}</i><b>${n}</b></span><span class="nav-arrow">›</span></button>`).join('')}</div>`).join('')}<div class="nav-footer"><span>Version</span><b>v${V424}</b></div>`;
  };
  renderSummary=function(){const el=document.getElementById('summary');if(el){el.innerHTML='';el.style.display='none'}};
  const baseTop424=renderTop;
  renderTop=function(){baseTop424();const d=document.getElementById('pageDesc');if(d)d.textContent='';const v=document.getElementById('versionBadge');if(v)v.textContent='v'+V424};

  // ---------- quality center ----------
  function pct424(v){if(v==null||isNaN(Number(v)))return '-';const n=Number(v);return (n<=1?n*100:n).toFixed(1)+'%'}
  function fmtSize424(n){n=Number(n||0);if(n<1024)return n+' B';if(n<1024**2)return(n/1024).toFixed(1)+' KB';if(n<1024**3)return(n/1024**2).toFixed(1)+' MB';return(n/1024**3).toFixed(2)+' GB'}
  function fmtTime424(sec){sec=Number(sec||0);if(!sec)return '-';if(sec<60)return Math.round(sec)+'秒';if(sec<3600)return Math.floor(sec/60)+'分'+Math.round(sec%60)+'秒';return Math.floor(sec/3600)+'小时'+Math.round(sec%3600/60)+'分'}
  function radar424(scores,cls=''){
    const entries=Object.entries(scores||{}); if(!entries.length)return '';
    const cx=150,cy=142,R=96,n=entries.length,points=(r)=>entries.map((_,i)=>{const a=-Math.PI/2+i*2*Math.PI/n;return`${cx+Math.cos(a)*r},${cy+Math.sin(a)*r}`}).join(' ');
    const valpts=entries.map(([k,v],i)=>{const a=-Math.PI/2+i*2*Math.PI/n,r=R*Math.max(0,Math.min(100,Number(v||0)))/100;return`${cx+Math.cos(a)*r},${cy+Math.sin(a)*r}`}).join(' ');
    const labels=entries.map(([k,v],i)=>{const a=-Math.PI/2+i*2*Math.PI/n,x=cx+Math.cos(a)*(R+25),y=cy+Math.sin(a)*(R+25);return`<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle">${esc(k)} ${Number(v||0).toFixed(0)}</text>`}).join('');
    return `<svg class="radar424 ${cls}" viewBox="0 0 300 285">${[.25,.5,.75,1].map(x=>`<polygon points="${points(R*x)}" class="radar-grid424"/>`).join('')}${entries.map((_,i)=>{const p=points(R).split(' ')[i];return`<line x1="${cx}" y1="${cy}" x2="${p.split(',')[0]}" y2="${p.split(',')[1]}" class="radar-axis424"/>`}).join('')}<polygon points="${valpts}" class="radar-value424"/>${labels}</svg>`;
  }
  window.renderQualityCenter424=async function(){
    document.getElementById('view').innerHTML='<div class="loading">正在计算质量指标...</div>';
    const r=await safe(api(`/api/v44/projects/${pid()}/quality-center`));state.quality424=r||{};const d=r?.dataset||{},a=r?.algorithm||{};
    const ascores={'Precision':a.avg_precision||0,'Recall':a.avg_recall||0,'mAP50':a.avg_map50||0,'训练成功率':a.train_success_rate||0,'版本覆盖率':a.version_coverage||0};
    const labels=Object.entries(d.label_boxes||{}).filter(([,v])=>v>0).sort((x,y)=>y[1]-x[1]);const max=Math.max(1,...labels.map(x=>x[1]));
    const algRows=(a.algorithms||[]).map(x=>`<tr><td><b>${esc(x.name)}</b></td><td>${esc(x.version||'-')}</td><td>${pct424(x.precision)}</td><td>${pct424(x.recall)}</td><td>${pct424(x.map50)}</td><td><b>${x.score==null?'-':Number(x.score).toFixed(1)}</b></td></tr>`).join('')||'<tr><td colspan="6">暂无已评测算法版本</td></tr>';
    document.getElementById('view').innerHTML=`<div class="quality424-shell"><div class="quality424-kpis"><div><span>数据质量</span><b>${d.overall_score||0}</b></div><div><span>素材数量</span><b>${d.images||0}</b></div><div><span>有效标注框</span><b>${d.box_count||0}</b></div><div><span>算法平均质量</span><b>${a.avg_score||0}</b></div><div><span>训练成功率</span><b>${a.train_success_rate||0}%</b></div></div><div class="quality424-grid"><section class="panel quality424-card"><div class="panel-head"><div class="panel-title">数据集质量维度</div></div><div class="panel-body quality424-radarbox">${radar424(d.scores||{})}<div class="quality424-facts"><div><span>已标注</span><b>${d.annotated_images||0}</b></div><div><span>标签数</span><b>${d.label_count||0}</b></div><div><span>重复图片</span><b>${d.duplicate_images||0}</b></div><div><span>低分辨率</span><b>${d.low_resolution||0}</b></div><div><span>无效框</span><b>${d.invalid_boxes||0}</b></div><div><span>数据体量</span><b>${fmtSize424(d.total_size_bytes)}</b></div></div></div></section><section class="panel quality424-card"><div class="panel-head"><div class="panel-title">算法质量维度</div></div><div class="panel-body quality424-radarbox">${radar424(ascores,'algorithm')}</div></section></div><div class="quality424-grid"><section class="panel"><div class="panel-head"><div class="panel-title">数据用途分布</div></div><div class="panel-body"><div class="splitbars424">${[['未处理','unassigned'],['训练集','train'],['试验集','val'],['评测集','test']].map(([n,k])=>{const v=d.split_counts?.[k]||0,all=Math.max(1,d.images||1);return`<div><span>${n}</span><div><i style="width:${v/all*100}%"></i></div><b>${v}</b></div>`}).join('')}</div></div></section><section class="panel"><div class="panel-head"><div class="panel-title">标签分布</div></div><div class="panel-body"><div class="labelbars424">${labels.map(([l,v])=>`<div><span>${esc(l)}</span><div><i style="width:${v/max*100}%"></i></div><b>${v}</b></div>`).join('')||'<div class="empty">暂无标签数据</div>'}</div></div></section></div><section class="panel"><div class="panel-head"><div class="panel-title">算法质量列表</div></div><div class="panel-body"><div class="table-wrap"><table class="table"><thead><tr><th>算法</th><th>版本</th><th>Precision</th><th>Recall</th><th>mAP50</th><th>质量分</th></tr></thead><tbody>${algRows}</tbody></table></div></div></section></div>`;
  };

  // ---------- single data pool ----------
  function splitName424(s){return({unassigned:'未处理',train:'训练集',val:'试验集',test:'评测集'})[s]||'未处理'}
  function dataRows424(){
    const tab=state.data424Tab,label=state.data424Label,q=(document.getElementById('data424Q')?.value||'').trim().toLowerCase();
    return (state.images||[]).filter(x=>((x.split||'unassigned')===tab)&&(!q||String(x.filename||'').toLowerCase().includes(q))&&(label==='all'||(x.labels||[]).includes(label)));
  }
  function renderDataRows424(){const box=document.getElementById('data424Rows');if(!box)return;const rows=dataRows424();box.innerHTML=rows.map(img=>`<tr><td><input type="checkbox" ${state.data424Selected.has(img.id)?'checked':''} onchange="selectData424('${img.id}',this.checked)"></td><td><div class="data424-name"><img src="${img.url}"><b title="${esc(img.filename)}">${esc(img.filename)}</b></div></td><td>${fmtSize424(img.size_bytes)}</td><td>${img.annotated?'<span class="pill ok">已标注</span>':'<span class="pill warn">未标注</span>'}</td><td>${(img.labels||[]).map(x=>`<span class="tag424">${esc(x)}</span>`).join('')||'-'}</td><td>${esc(String(img.created_at||'').replace('T',' ').slice(0,19))}</td><td><div class="row"><button class="btn mini" onclick="dataDetail424('${img.id}')">详情</button><button class="btn mini primary" onclick="openAnnotation('${img.id}')">标注</button><button class="btn mini danger" onclick="deleteData424('${img.id}')">删除</button></div></td></tr>`).join('')||'<tr><td colspan="7"><div class="empty">当前没有数据</div></td></tr>';
    const c=document.getElementById('data424Count');if(c)c.textContent=`${rows.length} 条`;
  }
  window.selectData424=(id,on)=>{on?state.data424Selected.add(id):state.data424Selected.delete(id)};
  window.setDataTab424=function(t){state.data424Tab=t;state.data424Selected.clear();renderDatasets424()};
  window.filterData424=function(){state.data424Label=document.getElementById('data424Label')?.value||'all';renderDataRows424()};
  window.renderDatasets424=function(){
    const counts={unassigned:0,train:0,val:0,test:0};(state.images||[]).forEach(x=>counts[(x.split||'unassigned') in counts?(x.split||'unassigned'):'unassigned']++);
    document.getElementById('view').innerHTML=`<section class="data424-shell"><div class="data424-head"><div class="data424-tabs">${[['未处理','unassigned'],['训练集','train'],['试验集','val'],['评测集','test']].map(([n,k])=>`<button class="${state.data424Tab===k?'on':''}" onclick="setDataTab424('${k}')"><span>${n}</span><b>${counts[k]}</b></button>`).join('')}</div><div class="row"><input id="data424Upload" type="file" multiple accept="image/*" class="file"><button class="btn primary" onclick="uploadData424()">上传图片</button><button class="btn" onclick="importData()">导入数据</button></div></div><section class="panel"><div class="data424-filter"><input id="data424Q" class="input" placeholder="搜索名称" oninput="renderDataRows424()"><select id="data424Label" class="select" onchange="filterData424()"><option value="all">全部标签</option>${(state.labels||[]).map(x=>`<option value="${esc(x.code)}" ${state.data424Label===x.code?'selected':''}>${esc(x.display_name||x.code)}</option>`).join('')}</select><select id="data424Move" class="select"><option value="">批量移动至...</option><option value="unassigned">未处理</option><option value="train">训练集</option><option value="val">试验集</option><option value="test">评测集</option></select><button class="btn" onclick="batchMoveData424()">应用</button><span id="data424Count" class="muted"></span></div><div class="table-wrap"><table class="table data424-table"><thead><tr><th></th><th>名称</th><th>大小</th><th>标注状态</th><th>标签</th><th>时间</th><th>操作</th></tr></thead><tbody id="data424Rows"></tbody></table></div></section></section>`;renderDataRows424();
  };
  window.uploadData424=async function(){const fs=[...(document.getElementById('data424Upload')?.files||[])];if(!fs.length)return toast('请选择图片');const fd=new FormData();fs.forEach(f=>fd.append('files',f));fd.append('dataset_id','default');try{await api(`/api/projects/${pid()}/images`,{method:'POST',body:fd});await loadRelated();renderDatasets424();toast(`已上传 ${fs.length} 张，进入未处理`)}catch(e){toast(e.message||e)}};
  window.batchMoveData424=async function(){const split=document.getElementById('data424Move')?.value;if(!split)return toast('请选择目标');const ids=[...state.data424Selected];if(!ids.length)return toast('请勾选数据');try{await api(`/api/v20/projects/${pid()}/images/batch_split`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:ids,split,scope:'selected'})});state.data424Selected.clear();await loadRelated();renderDatasets424();toast('已移动')}catch(e){toast(e.message||e)}};
  window.deleteData424=async id=>{if(!confirm('确认删除？'))return;await safe(api(`/api/projects/${pid()}/images/${id}`,{method:'DELETE'}));await loadRelated();renderDatasets424()};
  window.dataDetail424=function(id){const x=(state.images||[]).find(i=>i.id===id);if(!x)return;modal('素材详情',`<div class="data424-detail"><img src="${x.url}"><div class="detail422-grid"><div><span>名称</span><b>${esc(x.filename)}</b></div><div><span>大小</span><b>${fmtSize424(x.size_bytes)}</b></div><div><span>尺寸</span><b>${x.width} × ${x.height}</b></div><div><span>数据用途</span><b>${splitName424(x.split||'unassigned')}</b></div><div><span>标注状态</span><b>${x.annotated?'已标注':'未标注'}</b></div><div><span>标签</span><b>${esc((x.labels||[]).join('、')||'-')}</b></div><div><span>时间</span><b>${esc(String(x.created_at||'').replace('T',' ').slice(0,19))}</b></div></div></div>`,true)};

  // ---------- editable annotation boxes: move / resize / relabel ----------
  renderAnnSide=function(){
    const labels=state.labels||[],boxes=state.ann?.boxes||[];const lb=document.getElementById('annLabels'),bb=document.getElementById('annBoxes');if(!lb||!bb)return;
    lb.innerHTML=labels.map(l=>`<div class="label-row ${state.activeLabel===l.class_id?'active':''}" onclick="state.activeLabel=${l.class_id};renderAnnSide()"><span><span class="dot" style="background:${l.color}"></span>${esc(l.display_name||l.code)}</span><b>${esc(l.hotkey||'')}</b></div>`).join('');
    bb.innerHTML=boxes.map((b,i)=>`<div class="boxrow424 ${state.activeBox===i?'active':''}" onclick="state.activeBox=${i};drawBoxes();renderAnnSide()"><span>${i+1}</span><select class="select" onclick="event.stopPropagation()" onchange="changeBoxLabel424(${i},this.value)">${labels.map(l=>`<option value="${l.class_id}" ${l.class_id===b.class_id?'selected':''}>${esc(l.display_name||l.code)}</option>`).join('')}</select><b>${Math.round(b.x2-b.x1)}×${Math.round(b.y2-b.y1)}</b></div>`).join('')||'<div class="muted">暂无框</div>';
  };
  window.changeBoxLabel424=function(i,cid){const l=(state.labels||[]).find(x=>String(x.class_id)===String(cid));const b=state.ann?.boxes?.[i];if(!l||!b)return;pushHistory();b.class_id=l.class_id;b.label=l.code;state.activeBox=i;markDirty();drawBoxes();renderAnnSide()};
  drawBoxes=function(){const st=document.getElementById('annStage');if(!st)return;st.querySelectorAll('.box,.drawBox').forEach(x=>x.remove());const size=imageSize();(state.ann?.boxes||[]).forEach((b,i)=>{const l=(state.labels||[]).find(x=>x.class_id===b.class_id)||{};const el=document.createElement('div');el.className='box box424 '+(state.activeBox===i?'active':'');el.dataset.i=i;Object.assign(el.style,{left:b.x1/size.w*100+'%',top:b.y1/size.h*100+'%',width:(b.x2-b.x1)/size.w*100+'%',height:(b.y2-b.y1)/size.h*100+'%',borderColor:l.color||'#ef4444'});el.innerHTML=`<div class="boxTag" style="background:${l.color||'#ef4444'}">${esc(l.display_name||b.label)}</div>${state.activeBox===i?'<i class="handle424 nw" data-h="nw"></i><i class="handle424 ne" data-h="ne"></i><i class="handle424 sw" data-h="sw"></i><i class="handle424 se" data-h="se"></i>':''}`;el.onclick=e=>{e.stopPropagation();state.activeBox=i;drawBoxes();renderAnnSide()};st.appendChild(el)})};
  bindAnnotationEvents=function(){const st=document.getElementById('annStage'),im=document.getElementById('annImg');if(!st||!im||st.dataset.bound424==='1')return;st.dataset.bound424='1';let mode='',start=null,temp=null,boxIndex=-1,orig=null,handle='';function pos(e){const r=im.getBoundingClientRect(),size=imageSize();return{x:Math.max(0,Math.min(size.w,(e.clientX-r.left)/Math.max(1,r.width)*size.w)),y:Math.max(0,Math.min(size.h,(e.clientY-r.top)/Math.max(1,r.height)*size.h))}}function redrawTemp(p){if(!start||!temp)return;const size=imageSize(),x1=Math.min(start.x,p.x),y1=Math.min(start.y,p.y),x2=Math.max(start.x,p.x),y2=Math.max(start.y,p.y);Object.assign(temp.style,{left:x1/size.w*100+'%',top:y1/size.h*100+'%',width:(x2-x1)/size.w*100+'%',height:(y2-y1)/size.h*100+'%'})}st.addEventListener('mousedown',e=>{if(e.button!==0)return;const h=e.target.closest('.handle424'),bx=e.target.closest('.box424');start=pos(e);if(h&&bx){e.preventDefault();mode='resize';boxIndex=+bx.dataset.i;handle=h.dataset.h;orig={...state.ann.boxes[boxIndex]};pushHistory();return}if(bx){e.preventDefault();mode='move';boxIndex=+bx.dataset.i;orig={...state.ann.boxes[boxIndex]};state.activeBox=boxIndex;pushHistory();return}e.preventDefault();mode='draw';temp=document.createElement('div');temp.className='drawBox';st.appendChild(temp);redrawTemp(start)});window.addEventListener('mousemove',e=>{if(!mode||!start)return;const p=pos(e),size=imageSize();if(mode==='draw'){redrawTemp(p);return}const b=state.ann.boxes[boxIndex];if(!b)return;if(mode==='move'){const dx=p.x-start.x,dy=p.y-start.y,w=orig.x2-orig.x1,h=orig.y2-orig.y1;b.x1=Math.max(0,Math.min(size.w-w,orig.x1+dx));b.y1=Math.max(0,Math.min(size.h-h,orig.y1+dy));b.x2=b.x1+w;b.y2=b.y1+h}else{let x1=orig.x1,y1=orig.y1,x2=orig.x2,y2=orig.y2;if(handle.includes('w'))x1=Math.min(p.x,x2-3);if(handle.includes('e'))x2=Math.max(p.x,x1+3);if(handle.includes('n'))y1=Math.min(p.y,y2-3);if(handle.includes('s'))y2=Math.max(p.y,y1+3);Object.assign(b,{x1,y1,x2,y2})}markDirty();drawBoxes()});window.addEventListener('mouseup',e=>{if(!mode||!start)return;const p=pos(e);if(mode==='draw'){const x1=Math.min(start.x,p.x),y1=Math.min(start.y,p.y),x2=Math.max(start.x,p.x),y2=Math.max(start.y,p.y);temp?.remove();if(x2-x1>5&&y2-y1>5){const l=(state.labels||[]).find(x=>x.class_id===state.activeLabel)||state.labels[0];if(l){pushHistory();state.ann.boxes.push({id:String(Date.now()).slice(-10),class_id:l.class_id,label:l.code,x1:Math.round(x1),y1:Math.round(y1),x2:Math.round(x2),y2:Math.round(y2)});state.activeBox=state.ann.boxes.length-1;markDirty()}}}else{markDirty()}mode='';start=null;temp=null;boxIndex=-1;orig=null;drawBoxes();renderAnnSide()})};

  // ---------- video frame tasks ----------
  const videoCore424=()=>window.PlatformCore?.video;
  async function loadVideo424(){const rows=(await safe(api(`/api/v33/projects/${pid()}/video-tasks`)))?.items||[];state.video424=rows.map(t=>videoCore424()?.normalizeVideoTask(t)||t)}
  function taskStatus424(t){const c=['SUCCEEDED','PARTIAL_SUCCESS'].includes(t.status)?'ok':['FAILED','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE'].includes(t.status)?'err':'warn';return`<span class="pill ${c}">${esc(t.statusText||t.status)}</span>`}
  function videoTaskRow424(t){return`<tr data-task-id="${esc(t.id)}" data-updated-at="${esc(t.updated_at||'')}"><td><b>${esc(t.video_name||'-')}</b><div class="muted-line">${esc(t.id)}</div></td><td>${esc(t.samplingText||'-')}<div class="muted-line">最多 ${t.max_frames||'不限'} 张</div></td><td>${splitName424(t.split||'unassigned')}</td><td>${taskStatus424(t)}</td><td><div class="progress424"><i style="width:${t.progress||0}%"></i></div><span>${t.progress||0}% · ${t.extractedFrames||0}张</span></td><td>${esc(t.current_item||'-')}</td><td>${esc(String(t.created_at||'').slice(0,19))}<div class="muted-line">${esc(String(t.finished_at||'').slice(0,19))}</div></td><td><div class="row"><button class="btn mini" onclick="videoDetail424('${t.id}')">详情</button>${videoCore424()?.isActiveVideoTask(t)?`<button class="btn mini danger" onclick="stopVideo424('${t.id}')">停止</button>`:''}</div>${t.error?`<div class="alert err mini-alert">${esc(t.error)}</div>`:''}</td></tr>`}
  function patchVideoRows424(){const body=document.getElementById('video424Rows');if(!body)return;const seen=new Set();for(const t of state.video424||[]){seen.add(t.id);const old=body.querySelector(`[data-task-id="${CSS.escape(t.id)}"]`);if(old?.dataset.updatedAt===(t.updated_at||''))continue;const tpl=document.createElement('template');tpl.innerHTML=videoTaskRow424(t).trim();const next=tpl.content.firstElementChild;if(old)old.replaceWith(next);else body.appendChild(next)}body.querySelectorAll('[data-task-id]').forEach(row=>{if(!seen.has(row.dataset.taskId))row.remove()});const empty=body.querySelector('[data-video-empty]');if(state.video424.length)empty?.remove();else if(!empty)body.innerHTML='<tr data-video-empty><td colspan="8">暂无切帧任务</td></tr>'}
  window.refreshVideo424Delta=async function(){await loadVideo424();patchVideoRows424();window.PollRegistryRuntime?.replaceVideo424Timer?.()};
  window.renderVideo424=async function(){await loadVideo424();document.getElementById('view').innerHTML=`<section class="taskpage424"><div class="taskpage424-head"><div></div><button class="btn primary" onclick="createVideoTask424()">＋ 创建切帧任务</button></div><section class="panel"><div class="table-wrap"><table class="table task424-table"><thead><tr><th>视频</th><th>切帧方式</th><th>素材归属</th><th>状态</th><th>进度</th><th>当前帧</th><th>创建/完成</th><th>操作</th></tr></thead><tbody id="video424Rows">${state.video424.map(videoTaskRow424).join('')||'<tr data-video-empty><td colspan="8">暂无切帧任务</td></tr>'}</tbody></table></div></section></section>`;window.PollRegistryRuntime?.replaceVideo424Timer?.()};
  window.createVideoTask424=function(){modal('创建切帧任务',`<div class="form two"><div class="field full"><label>上传视频文件</label><input id="vf424File" type="file" class="file" accept="video/*" onchange="videoEstimate424()"></div><div class="field"><label>切帧方式</label><select id="vf424Mode" class="select" onchange="videoMode424();videoEstimate424()"><option value="interval_seconds">按时间间隔</option><option value="fps">按每秒帧数</option><option value="fixed_count">按固定帧数</option></select></div><div class="field"><label>素材归属</label><select id="vf424Split" class="select"><option value="unassigned">未处理</option><option value="train">训练集</option><option value="val">验证集</option><option value="test">试验集</option></select></div><div class="field" id="vf424IntervalBox"><label>切帧间隔（秒）</label><input id="vf424Interval" class="input" type="number" min="0.05" step="0.05" value="1" oninput="videoEstimate424()"></div><div class="field hidden" id="vf424FpsBox"><label>每秒抽取帧数</label><input id="vf424Fps" class="input" type="number" min="0.1" step="0.1" value="1" oninput="videoEstimate424()"></div><div class="field hidden" id="vf424FixedBox"><label>固定抽取帧数</label><input id="vf424Fixed" class="input" type="number" min="1" step="1" value="50" oninput="videoEstimate424()"></div><div class="field"><label>最大切帧数量（可选）</label><input id="vf424Max" class="input" type="number" min="0" value="0" oninput="videoEstimate424()"></div><div class="field full"><div id="vf424Estimate" class="estimate424">选择视频后计算预计帧数</div></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="submitVideo424()">创建任务</button></div>`,true)};
  window.videoMode424=function(){const mode=document.getElementById('vf424Mode')?.value;document.getElementById('vf424IntervalBox')?.classList.toggle('hidden',mode!=='interval_seconds');document.getElementById('vf424FpsBox')?.classList.toggle('hidden',mode!=='fps');document.getElementById('vf424FixedBox')?.classList.toggle('hidden',mode!=='fixed_count')};
  window.videoEstimate424=function(){const f=document.getElementById('vf424File')?.files?.[0],out=document.getElementById('vf424Estimate');if(!f||!out)return;const v=document.createElement('video');v.preload='metadata';v.onloadedmetadata=()=>{const dur=v.duration||0,mode=document.getElementById('vf424Mode')?.value,max=+(document.getElementById('vf424Max')?.value||0);let n=mode==='fps'?dur*(+(document.getElementById('vf424Fps')?.value||1)):mode==='fixed_count'?+(document.getElementById('vf424Fixed')?.value||1):dur/Math.max(.05,+(document.getElementById('vf424Interval')?.value||1));if(max>0)n=Math.min(n,max);out.textContent=`视频约 ${dur.toFixed(1)} 秒 · 预计生成 ${Math.ceil(n)} 张`;URL.revokeObjectURL(v.src)};v.src=URL.createObjectURL(f)};
  window.submitVideo424=async function(){const f=document.getElementById('vf424File')?.files?.[0];if(!f)return toast('请选择视频');const mode=document.getElementById('vf424Mode').value,fd=new FormData();let values;try{values=videoCore424().videoTaskFormValues(mode,{intervalSeconds:document.getElementById('vf424Interval')?.value,extractFps:document.getElementById('vf424Fps')?.value,fixedCount:document.getElementById('vf424Fixed')?.value,maxFrames:document.getElementById('vf424Max')?.value})}catch(e){return toast(e.message||e)}fd.append('video',f);fd.append('dataset_id','default');fd.append('split',document.getElementById('vf424Split').value);fd.append('backend','auto');for(const [key,value] of Object.entries(values))fd.append(key,String(value));try{await api(`/api/v33/projects/${pid()}/video-tasks`,{method:'POST',body:fd});closeModal();await refreshVideo424Delta();toast('切帧任务已创建')}catch(e){toast(e.message||e)}};
  window.stopVideo424=async id=>{await safe(api(`/api/v33/projects/${pid()}/video-tasks/${id}/stop`,{method:'POST'}));await refreshVideo424Delta()};
  window.videoDetail424=id=>{const t=state.video424.find(x=>x.id===id);if(t)modal('切帧任务详情',`<div class="detail422-grid"><div><span>视频</span><b>${esc(t.video_name)}</b></div><div><span>状态</span><b>${esc(t.statusText||t.status)}</b></div><div><span>素材归属</span><b>${splitName424(t.split||'unassigned')}</b></div><div><span>已生成</span><b>${t.extractedFrames||0} 张</b></div><div><span>进度</span><b>${t.progress||0}%</b></div><div><span>输出目录</span><b>${esc(t.result?.output_ref||'-')}</b></div></div>${t.error?`<div class="alert err">${esc(t.error)}</div>`:''}`,true)};

  // ---------- automatic annotation task page ----------
  async function loadPrelabel424(){state.prelabel424=(await safe(api(`/api/v33/projects/${pid()}/prelabel-tasks`)))?.items||[]}
  window.renderAutoLabel424=async function(){await loadPrelabel424();document.getElementById('view').innerHTML=`<section class="taskpage424"><div class="taskpage424-head"><div></div><button class="btn primary" onclick="createPrelabel424()">＋ 创建自动标注任务</button></div><section class="panel"><div class="table-wrap"><table class="table task424-table"><thead><tr><th>任务</th><th>模型 / 标签</th><th>处理范围</th><th>状态</th><th>进度</th><th>预计剩余</th><th>创建/完成</th><th>操作</th></tr></thead><tbody>${state.prelabel424.map(t=>`<tr><td><b>${esc(t.name||t.id)}</b><div class="muted-line">${esc(t.id)}</div></td><td>${esc(t.model_name||'-')}<div class="muted-line">${esc(t.target_label||'-')}</div></td><td>${t.total_images||0} 张</td><td>${taskStatus424(t)}</td><td><div class="progress424"><i style="width:${t.progress||0}%"></i></div><span>${t.processed_images||0}/${t.total_images||0} · ${t.boxes_added||0}框</span></td><td>${fmtTime424(t.eta_seconds)}</td><td>${esc(String(t.created_at||'').slice(0,19))}<div class="muted-line">${esc(String(t.finished_at||'').slice(0,19))}</div></td><td><div class="row"><button class="btn mini" onclick="prelabelDetail424('${t.id}')">详情</button>${['queued','running'].includes(t.status)?`<button class="btn mini danger" onclick="stopPrelabel424('${t.id}')">停止</button>`:''}${['failed','stopped'].includes(t.status)?`<button class="btn mini primary" onclick="retryPrelabel424('${t.id}')">重试</button>`:''}</div></td></tr>`).join('')||'<tr><td colspan="8">暂无自动标注任务</td></tr>'}</tbody></table></div></section></section>`;};
  window.createPrelabel424=function(){const models=state.modelConfigs||[],labels=state.labels||[];modal('创建自动标注任务',`<div class="form two"><div class="field"><label>任务名称</label><input id="pl424Name" class="input" value="自动标注-${new Date().toLocaleDateString()}"></div><div class="field"><label>模型</label><select id="pl424Model" class="select">${models.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')}</select></div><div class="field"><label>素材范围</label><select id="pl424Split" class="select" onchange="prelabelEstimate424()"><option value="unassigned">未处理</option><option value="train">训练集</option><option value="val">试验集</option><option value="test">评测集</option><option value="all">全部</option></select></div><div class="field"><label>目标标签</label><select id="pl424Label" class="select">${labels.map(x=>`<option value="${esc(x.code)}">${esc(x.display_name||x.code)}</option>`).join('')}</select></div><div class="field"><label>置信度阈值</label><input id="pl424Threshold" class="input" type="number" min="0" max="1" step="0.05" value="0.5"></div><div class="field check"><label><input id="pl424OnlyUn" type="checkbox" checked onchange="prelabelEstimate424()"> 仅处理未标注图片</label></div><div class="field full"><label>提示词（模型需要时）</label><textarea id="pl424Prompt"></textarea></div><div class="field check"><label><input id="pl424Overwrite" type="checkbox"> 覆盖同标签旧框</label></div><div class="field full"><div id="pl424Estimate" class="estimate424"></div></div></div><div class="row between"><button class="btn" onclick="testPrelabelModel424()">检测模型</button><div class="row"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="submitPrelabel424()">创建任务</button></div></div>`,true);setTimeout(prelabelEstimate424,0)};
  function prelabelIds424(){const sp=document.getElementById('pl424Split')?.value||'unassigned',only=document.getElementById('pl424OnlyUn')?.checked;return(state.images||[]).filter(x=>(sp==='all'||(x.split||'unassigned')===sp)&&(!only||!x.annotated)).map(x=>x.id)}
  window.prelabelEstimate424=function(){const ids=prelabelIds424(),out=document.getElementById('pl424Estimate');if(!out)return;const hist=(state.prelabel424||[]).filter(x=>x.elapsed_seconds&&x.processed_images);let spi=hist.length?hist.reduce((s,x)=>s+x.elapsed_seconds/Math.max(1,x.processed_images),0)/hist.length:null;out.textContent=`将处理 ${ids.length} 张${spi?` · 按历史速度预计 ${fmtTime424(spi*ids.length)}`:' · 任务开始后将按实际模型速度动态计算剩余时间'}`};
  window.testPrelabelModel424=async function(){const id=document.getElementById('pl424Model')?.value,c=(state.modelConfigs||[]).find(x=>x.id===id);if(!c)return toast('请先配置模型');try{await api(`/api/v44/model-configs/${c.id}/test`,{method:'POST'});toast('模型连接正常')}catch(e){toast(e.message||e)}};
  window.submitPrelabel424=async function(){const ids=prelabelIds424(),model=document.getElementById('pl424Model')?.value;if(!ids.length)return toast('没有符合条件的图片');if(!model)return toast('请选择模型');const body={model_config_id:model,prompt:document.getElementById('pl424Prompt').value||'',threshold:+document.getElementById('pl424Threshold').value||.5,target_label:document.getElementById('pl424Label').value||'person',image_ids:ids,overwrite:document.getElementById('pl424Overwrite').checked,task_name:document.getElementById('pl424Name').value||'自动标注任务',training_framework:'internal',dataset_id:'default'};try{await api(`/api/v35/projects/${pid()}/prelabel-tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeModal();renderAutoLabel424();toast('自动标注任务已创建')}catch(e){toast(e.message||e)}};
  window.stopPrelabel424=async id=>{await safe(api(`/api/v33/projects/${pid()}/prelabel-tasks/${id}/stop`,{method:'POST'}));renderAutoLabel424()};
  window.prelabelDetail424=id=>{const t=state.prelabel424.find(x=>x.id===id);if(t)modal('自动标注任务详情',`<div class="detail422-grid"><div><span>模型</span><b>${esc(t.model_name||'-')}</b></div><div><span>标签</span><b>${esc(t.target_label||'-')}</b></div><div><span>处理图片</span><b>${t.processed_images||0}/${t.total_images||0}</b></div><div><span>新增框</span><b>${t.boxes_added||0}</b></div><div><span>状态</span><b>${esc(t.status_text||t.status)}</b></div><div><span>预计剩余</span><b>${fmtTime424(t.eta_seconds)}</b></div></div>${t.error?`<div class="error-box422">${esc(t.error)}</div>`:''}`,true)};
  window.retryPrelabel424=async id=>{const t=state.prelabel424.find(x=>x.id===id),body=t?.request_payload;if(!body)return toast('旧任务缺少重试参数');try{await api(`/api/v35/projects/${pid()}/prelabel-tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});renderAutoLabel424();toast('已重新创建任务')}catch(e){toast(e.message||e)}};

  // ---------- training task first + output/report + data quality ----------
  function trainStatus424(j){return taskStatus424({status:j.status,status_text:j.status_text||j.status})}
  function jobRows424(){return(state.jobs||[]).map(j=>{const open=!!state.train424Expanded[j.id],mods=j.models||[];return`<tbody class="trainjob424"><tr onclick="toggleTrain424('${j.id}')"><td><b>${esc(j.asset_algorithm_name||j.algorithm_name||j.id)}</b><div class="muted-line">${esc(j.id)}</div></td><td>${trainStatus424(j)}</td><td>${esc(j.framework==='paddle'?'PaddleDetection':'Ultralytics / YOLO')}</td><td>训练 ${j.dataset_counts?.train||0} / 试验 ${j.dataset_counts?.val||0}</td><td><div class="progress424"><i style="width:${j.progress_percent||0}%"></i></div><span>${j.current_epoch||0}/${j.total_epochs||j.epochs||0} · ${j.elapsed_text||'-'}</span></td><td>${j.eta_text||'-'}</td><td>${esc(String(j.created_at||'').slice(0,19))}</td><td><div class="row"><button class="btn mini" onclick="event.stopPropagation();showTrainLog423('${j.id}')">日志</button><button class="btn mini primary" onclick="event.stopPropagation();trainingReport424('${j.id}')">训练报告</button>${['queued','running'].includes(j.status)?`<button class="btn mini danger" onclick="event.stopPropagation();stopJob423('${j.id}')">停止</button>`:''}</div></td></tr>${open?`<tr class="trainjob424-output"><td colspan="8"><div class="trainoutput424"><div><span>关联算法</span><b>${esc(j.asset_algorithm_name||'未关联')}</b></div><div><span>训练结果</span><b>${esc(j.training_outcome==='target_reached'?'达到目标提前完成':j.training_outcome==='needs_optimization'?'未达门槛，建议优化':j.status==='done'?'训练完成':'训练中')}</b></div><div class="grow"><span>成果模型</span><div class="row wrap">${mods.map(m=>`<span class="artifact424">${esc(String(m).split(/[\\/]/).pop())}</span>`).join('')||'<span class="muted">暂无成果</span>'}</div></div></div></td></tr>`:''}</tbody>`}).join('')||'<tbody><tr><td colspan="8">暂无训练任务</td></tr></tbody>'}
  window.renderTraining424=function(){document.getElementById('view').innerHTML=`<section class="taskpage424"><div class="taskpage424-head"><div></div><button class="btn primary" onclick="openTrain424()">▶ 开始训练</button></div><section class="panel"><div class="table-wrap"><table class="table train424-table"><thead><tr><th>训练任务</th><th>状态</th><th>框架</th><th>数据</th><th>进度 / 已用</th><th>预计剩余</th><th>创建时间</th><th>操作</th></tr></thead>${jobRows424()}</table></div></section></section>`};
  window.toggleTrain424=id=>{state.train424Expanded[id]=!state.train424Expanded[id];renderTraining424()};
  function algMeta424(a){const b=(state.v42?.blueprints||[]).find(x=>x.algorithm_id===a.id)||{};return{type:a.algorithm_type||b.algorithm_type||'yolo_ultralytics'}}
  function trainTargets424(a){const type=algMeta424(a).type;return(state.targets||[]).filter(t=>t.status==='ready'&&((type==='paddle_detection'&&t.framework==='paddle')||(type!=='paddle_detection'&&t.framework!=='paddle')))}
  function baseTrainConfig424(){return{epochs:100,imgsz:640,batch:8,device:'cpu',optimizer:'auto',patience:100,workers:0,lr0:.01,lrf:.01,weight_decay:.0005,close_mosaic:10,mosaic:1,cache:'False',pretrained:true,amp:true,rect:false,cos_lr:false,freeze:0,eval_interval:10,eval_metric:'map50',continue_threshold:.5,stop_threshold:.9,val_max_samples:100,auto_supplement:false,supplement_count:50}}
  function initTrainSelections424(){
    state.train424Selected={train:new Set((state.images||[]).filter(x=>(x.split||'unassigned')==='train'&&x.annotated).map(x=>x.id)),val:new Set((state.images||[]).filter(x=>(x.split||'unassigned')==='val'&&x.annotated).map(x=>x.id))};
  }
  function selectedTrainIds424(split){return [...(state.train424Selected?.[split]||new Set())]}
  function selectedLabelSummary424(split){const ids=new Set(selectedTrainIds424(split)),labs=new Set();(state.images||[]).filter(x=>ids.has(x.id)).forEach(x=>(x.labels||[]).forEach(l=>labs.add(l)));return [...labs].join('、')||'-'}
  window.openTrain424=function(aid=''){state.train424Config=baseTrainConfig424();initTrainSelections424();const algs=state.algorithms||[],a=algs.find(x=>x.id===aid)||algs[0];modal('创建训练任务',`<div class="train424-create"><div class="form two"><div class="field"><label>算法</label><select id="tr424Alg" class="select" onchange="trainAlg424()">${algs.map(x=>`<option value="${x.id}" ${x.id===a?.id?'selected':''}>${esc(x.name)}</option>`).join('')}</select></div><div class="field"><label>训练资源</label><select id="tr424Target" class="select" onchange="trainTarget424()"></select></div></div><div class="train424-data"><div class="train424-data-card"><div class="row between"><div><b>训练集</b><span id="tr424TrainCount"></span></div><div class="row"><button class="btn mini" onclick="openTrainDataPicker424('train')">选择数据</button><button class="btn mini" onclick="trainDataQuality424('train')">查看数据质量</button></div></div><div class="train424-selection"><span>已选标签</span><b id="tr424TrainLabelSummary">-</b></div></div><div class="train424-data-card"><div class="row between"><div><b>试验集</b><span id="tr424ValCount"></span></div><div class="row"><button class="btn mini" onclick="openTrainDataPicker424('val')">选择数据</button><button class="btn mini" onclick="trainDataQuality424('val')">查看数据质量</button></div></div><div class="train424-selection"><span>已选标签</span><b id="tr424ValLabelSummary">-</b></div></div></div><div class="train424-config-summary"><div><span>基础模型</span><b id="tr424ModelText">-</b></div><div><span>训练轮数</span><b id="tr424EpochText">100</b></div><div><span>图片尺寸</span><b id="tr424SizeText">640</b></div><div><span>Batch</span><b id="tr424BatchText">8</b></div><button class="btn" onclick="openTrainSettings424()">配置设置</button></div><div id="tr424Estimate" class="estimate424"></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="submitTrain424()">开始训练</button></div></div>`,true);setTimeout(()=>{trainAlg424();trainDataCounts424()},20)};
  function pickerRows424(){const split=state.train424PickerSplit,draft=state.train424PickerDraft||new Set(),q=(document.getElementById('tdp424Q')?.value||'').trim().toLowerCase(),label=document.getElementById('tdp424Label')?.value||'all';const rows=(state.images||[]).filter(x=>(x.split||'unassigned')===split&&x.annotated&&(!q||String(x.filename||'').toLowerCase().includes(q))&&(label==='all'||(x.labels||[]).includes(label)));const box=document.getElementById('tdp424Rows');if(box)box.innerHTML=rows.map(x=>`<tr><td><input type="checkbox" ${draft.has(x.id)?'checked':''} onchange="toggleTrainPicker424('${x.id}',this.checked)"></td><td><b>${esc(x.filename)}</b></td><td>${(x.labels||[]).map(l=>`<span class="tag424">${esc(l)}</span>`).join('')}</td><td>${fmtSize424(x.size_bytes)}</td></tr>`).join('')||'<tr><td colspan="4">无符合条件的数据</td></tr>';const c=document.getElementById('tdp424Count');if(c)c.textContent=`已选 ${draft.size} 张 / 当前筛选 ${rows.length} 张`;return rows}
  window.openTrainDataPicker424=function(split){state.train424PickerSplit=split;state.train424PickerDraft=new Set(selectedTrainIds424(split));modal(`${split==='train'?'训练集':'试验集'} · 选择数据`,`<div class="trainpicker424"><div class="data424-filter"><input id="tdp424Q" class="input" placeholder="搜索名称" oninput="pickerRows424()"><select id="tdp424Label" class="select" onchange="pickerRows424()"><option value="all">全部标签</option>${(state.labels||[]).map(l=>`<option value="${esc(l.code)}">${esc(l.display_name||l.code)}</option>`).join('')}</select><button class="btn" onclick="selectFilteredTrain424(true)">全选筛选结果</button><button class="btn" onclick="selectFilteredTrain424(false)">取消筛选结果</button><span id="tdp424Count"></span></div><div class="table-wrap trainpicker424-list"><table class="table"><thead><tr><th></th><th>名称</th><th>标签</th><th>大小</th></tr></thead><tbody id="tdp424Rows"></tbody></table></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="applyTrainPicker424()">确定</button></div></div>`,true);setTimeout(pickerRows424,10)};
  window.pickerRows424=pickerRows424;
  window.toggleTrainPicker424=(id,on)=>{on?state.train424PickerDraft.add(id):state.train424PickerDraft.delete(id);const c=document.getElementById('tdp424Count');if(c)c.textContent=`已选 ${state.train424PickerDraft.size} 张`};
  window.selectFilteredTrain424=function(on){const rows=pickerRows424();rows.forEach(x=>on?state.train424PickerDraft.add(x.id):state.train424PickerDraft.delete(x.id));pickerRows424()};
  window.applyTrainPicker424=function(){state.train424Selected[state.train424PickerSplit]=new Set(state.train424PickerDraft);closeModal();trainDataCounts424()};
  window.trainDataCounts424=function(){const tc=selectedTrainIds424('train').length,vc=selectedTrainIds424('val').length;const a=document.getElementById('tr424TrainCount'),b=document.getElementById('tr424ValCount');if(a)a.textContent=`${tc} 张`;if(b)b.textContent=`${vc} 张`;const al=document.getElementById('tr424TrainLabelSummary'),bl=document.getElementById('tr424ValLabelSummary');if(al)al.textContent=selectedLabelSummary424('train');if(bl)bl.textContent=selectedLabelSummary424('val');const out=document.getElementById('tr424Estimate'),hist=(state.jobs||[]).filter(j=>j.status==='done'&&j.elapsed_seconds&&j.epochs);if(out){if(hist.length&&tc){const per=hist.map(j=>j.elapsed_seconds/Math.max(1,j.epochs)/Math.max(1,j.dataset_counts?.train||tc));const secPerEpochPerImage=per.reduce((s,x)=>s+x,0)/per.length;out.textContent=`按历史训练速度估算：约 ${fmtTime424(secPerEpochPerImage*tc*(state.train424Config?.epochs||100))}`;}else out.textContent='任务开始后会根据实际 Epoch 速度动态计算预计剩余时间';}}
  window.trainDataQuality424=async function(split){const ids=selectedTrainIds424(split);if(!ids.length)return toast(`请先选择${split==='train'?'训练集':'试验集'}数据`);try{const r=await api(`/api/v44/projects/${pid()}/data-quality`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({split,image_ids:ids})}),q=r.quality||{};modal(`${split==='train'?'训练集':'试验集'} · 数据质量`,`<div class="qualitypopup424"><div class="qualitypopup424-score"><b>${q.overall_score||0}</b><span>综合质量</span></div>${radar424(q.scores||{})}<div class="quality424-facts"><div><span>图片</span><b>${q.images||0}</b></div><div><span>已标注</span><b>${q.annotated_images||0}</b></div><div><span>标签</span><b>${q.label_count||0}</b></div><div><span>标注框</span><b>${q.box_count||0}</b></div><div><span>重复</span><b>${q.duplicate_images||0}</b></div><div><span>低分辨率</span><b>${q.low_resolution||0}</b></div></div><div class="labelbars424">${Object.entries(q.label_boxes||{}).filter(([,v])=>v>0).map(([l,v])=>`<div><span>${esc(l)}</span><div><i style="width:${Math.min(100,v/Math.max(1,...Object.values(q.label_boxes||{}))*100)}%"></i></div><b>${v}</b></div>`).join('')}</div></div>`,true)}catch(e){toast(e.message||e)}};
  window.trainAlg424=function(){const a=(state.algorithms||[]).find(x=>x.id===document.getElementById('tr424Alg')?.value),sel=document.getElementById('tr424Target');if(!a||!sel)return;const ts=trainTargets424(a);sel.innerHTML=ts.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join('')||'<option value="">无可用训练资源</option>';trainTarget424()};
  window.trainTarget424=function(){const t=(state.targets||[]).find(x=>x.id===document.getElementById('tr424Target')?.value),c=state.train424Config||baseTrainConfig424();if(t){c.device=t.type==='server'?'0':(t.recommendation?.device||'cpu');const m=(t.base_models||[])[0];c.model=m?.value||m?.label||'';}state.train424Config=c;refreshTrainSummary424()};
  function refreshTrainSummary424(){const c=state.train424Config||{};const sets=[['tr424ModelText',String(c.model||'-').split(/[\\/]/).pop()],['tr424EpochText',c.epochs],['tr424SizeText',c.imgsz],['tr424BatchText',c.batch]];sets.forEach(([id,v])=>{const e=document.getElementById(id);if(e)e.textContent=v});trainDataCounts424()}
  window.openTrainSettings424=function(){const c=state.train424Config||baseTrainConfig424();modal('训练配置设置',`<div class="form two"><div class="field"><label>基础模型</label><input id="ts424Model" class="input" value="${esc(c.model||'')}"></div><div class="field"><label>训练轮数</label><input id="ts424Epochs" class="input" type="number" value="${c.epochs}"></div><div class="field"><label>图片尺寸</label><input id="ts424Size" class="input" type="number" value="${c.imgsz}"></div><div class="field"><label>Batch</label><input id="ts424Batch" class="input" type="number" value="${c.batch}"></div><div class="field"><label>优化器</label><select id="ts424Opt" class="select"><option>auto</option><option>SGD</option><option>AdamW</option><option>Adam</option></select></div><div class="field"><label>早停 patience</label><input id="ts424Patience" class="input" type="number" value="${c.patience}"></div></div><div class="divider"></div><div class="form two"><div class="field"><label>每隔多少轮检查一次</label><input id="ts424EvalInt" class="input" type="number" min="0" value="${c.eval_interval}"></div><div class="field"><label>检查指标</label><select id="ts424Metric" class="select"><option value="map50" ${c.eval_metric==='map50'?'selected':''}>mAP50</option><option value="recall" ${c.eval_metric==='recall'?'selected':''}>Recall</option><option value="precision" ${c.eval_metric==='precision'?'selected':''}>Precision</option></select></div><div class="field"><label>低于此值停止并优化</label><input id="ts424Continue" class="input" type="number" min="0" max="1" step="0.01" value="${c.continue_threshold}"></div><div class="field"><label>达到此值提前完成</label><input id="ts424Stop" class="input" type="number" min="0" max="1" step="0.01" value="${c.stop_threshold}"></div><div class="field"><label>试验集最多使用图片</label><input id="ts424ValMax" class="input" type="number" min="0" value="${c.val_max_samples}"></div><div class="field"><label>弱标签补充数量</label><input id="ts424Supplement" class="input" type="number" min="0" value="${c.supplement_count}"></div><div class="field check"><label><input id="ts424AutoSupplement" type="checkbox" ${c.auto_supplement?'checked':''}> 训练报告发现弱标签后允许一键补充同标签未处理素材</label></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveTrainSettings424()">保存配置</button></div>`,true)};
  window.saveTrainSettings424=function(){const c=state.train424Config||{};Object.assign(c,{model:document.getElementById('ts424Model').value,epochs:+document.getElementById('ts424Epochs').value||100,imgsz:+document.getElementById('ts424Size').value||640,batch:+document.getElementById('ts424Batch').value||8,optimizer:document.getElementById('ts424Opt').value||'auto',patience:+document.getElementById('ts424Patience').value||100,eval_interval:+document.getElementById('ts424EvalInt').value||0,eval_metric:document.getElementById('ts424Metric').value||'map50',continue_threshold:+document.getElementById('ts424Continue').value||0,stop_threshold:+document.getElementById('ts424Stop').value||0,val_max_samples:+document.getElementById('ts424ValMax').value||0,supplement_count:+document.getElementById('ts424Supplement').value||0,auto_supplement:document.getElementById('ts424AutoSupplement').checked});state.train424Config=c;closeModal();refreshTrainSummary424();toast('训练配置已保存')};
    window.trainingReport424=async function(id){try{const r=await api(`/api/v44/projects/${pid()}/jobs/${id}/report`),j=r.job||{},rep=r.report||{},m=rep.metrics||{},pcs=rep.per_class||[];modal('训练报告',`<div class="report424"><div class="report424-head"><div><span>任务</span><b>${esc(j.asset_algorithm_name||j.algorithm_name||j.id)}</b></div><div><span>训练结果</span><b>${esc(j.training_outcome==='target_reached'?'达到目标提前完成':j.training_outcome==='needs_optimization'?'未达质量门槛':j.status_text||j.status)}</b></div><div><span>耗时</span><b>${esc(j.elapsed_text||'-')}</b></div><div><span>成果</span><b>${(j.models||[]).length} 个模型</b></div></div><div class="report424-metrics"><div><span>Precision</span><b>${pct424(m['metrics/precision(B)'])}</b></div><div><span>Recall</span><b>${pct424(m['metrics/recall(B)'])}</b></div><div><span>mAP50</span><b>${pct424(m['metrics/mAP50(B)'])}</b></div><div><span>mAP50-95</span><b>${pct424(m['metrics/mAP50-95(B)'])}</b></div></div>${rep.quality_gate_reason?`<div class="estimate424">${esc(rep.quality_gate_reason)}</div>`:''}<section class="report424-section"><b>阶段检查</b><div class="timeline424">${(rep.gate_events||[]).map(e=>`<div><span>Epoch ${e.epoch}</span><b>${esc(e.metric)} ${e.value==null?'-':pct424(e.value)}</b><em>${esc(e.decision||'')}</em></div>`).join('')||'<span class="muted">未启用阶段门禁</span>'}</div></section><section class="report424-section"><b>各标签效果</b><table class="table"><thead><tr><th>标签</th><th>Precision</th><th>Recall</th><th>mAP50</th></tr></thead><tbody>${pcs.map(x=>`<tr><td>${esc(x.label)}</td><td>${pct424(x.precision)}</td><td>${pct424(x.recall)}</td><td>${pct424(x.map50)}</td></tr>`).join('')||'<tr><td colspan="4">暂无逐标签指标</td></tr>'}</tbody></table></section><section class="report424-section"><b>错误样本分析</b><div class="error424-list">${(rep.error_samples||[]).filter(x=>!x.analysis_error).slice(0,100).map(x=>`<div><b>${esc(x.image)}</b><span>漏检 ${x.false_negative_count||0} · ${esc((x.false_negative_labels||[]).join('、')||'-')}</span><span>误检 ${x.false_positive_count||0} · ${esc((x.false_positive_labels||[]).join('、')||'-')}</span></div>`).join('')||'<span class="muted">未发现可列出的错误样本或尚未生成错误分析</span>'}</div></section>${(rep.weak_labels||[]).length?`<div class="report424-weak"><b>弱标签：${esc(rep.weak_labels.join('、'))}</b><span>这些标签和错误样本由模型预测与人工标准标注对比计算，不由大模型主观判断。</span>${j.quality_gate?.auto_supplement?`<button class="btn primary" onclick="supplementTrain424('${id}')">从未处理补充同标签素材</button>`:''}</div>`:''}</div>`,true)}catch(e){toast(e.message||e)}};
  window.supplementTrain424=async id=>{try{const r=await api(`/api/v44/projects/${pid()}/jobs/${id}/supplement`,{method:'POST'});toast(`已补充 ${r.changed||0} 张到训练集`);await loadRelated()}catch(e){toast(e.message||e)}};

  // ---------- deployment cache ----------
  window.showVersionDeployments423=async function(aid,vid){const key=`cl_deploy_version_${pid()}_${aid}_${vid}`,ttl=10*60*1000;let r=null;try{const c=JSON.parse(localStorage.getItem(key)||'null');if(c)r=c.data}catch(e){}if(!r){try{r=await api(`/api/v42/projects/${pid()}/algorithms/${aid}/versions/${vid}/deployments`);localStorage.setItem(key,JSON.stringify({ts:Date.now(),data:r}))}catch(e){return toast(e.message||e)}}const v=r.version||{},items=r.items||[];modal(`${r.algorithm?.name||'算法'} · ${v.version_name||'版本'} · 部署产物`,`<div class="deploy423-source"><span>源模型</span><b>${esc(v.model_name||'')}</b><em>${Number(v.size_mb||0).toFixed(2)} MB</em></div><div class="deploy423-list">${items.map(j=>`<div class="deploy423-job"><div class="deploy423-job-head"><div><b>${esc(j.target_name||j.target)}</b>${taskStatus424(j)}</div><time>${esc(String(j.finished_at||j.created_at||'').slice(0,19))}</time></div><div class="deploy423-job-meta"><span>转换资源：${esc(j.resource_name||'-')}</span><span>任务：${esc(j.id)}</span></div><div class="deploy423-files">${(j.outputs||[]).map(o=>`<div><span>${esc(o.name)}</span><b>${o.size_mb!=null?Number(o.size_mb).toFixed(2)+' MB':''}</b>${o.download_url?`<a class="btn mini" href="${o.download_url}">下载</a>`:''}</div>`).join('')||'<div>暂无输出文件</div>'}</div></div>`).join('')||'<div class="empty">暂无部署产物</div>'}</div>`,true)};

  // Final route override
  const renderBase424=render;
  render=function(){
    renderNav();renderTop();renderSummary();
    if(state.page==='质量中心'){renderQualityCenter424();return}
    if(state.page==='视频切帧'){renderVideo424();return}
    // algorithm/data/training routes are owned by later stable wrappers.
    renderBase424();
  };
})();

/* ============================================================
   v42.5 — mature training workflow + visual data picker + reports
   ============================================================ */
(()=>{
  const V425='42.24.0';
  const prevLoad425=loadRelated;
  loadRelated=async function(){
    await prevLoad425();
    if(state.project){state.modelConfigs=(await safe(api('/api/v35/model-configs')))?.items||[];}
  };

  function cfg425(){return {
    model:'',epochs:100,imgsz:640,batch:8,device:'cpu',optimizer:'auto',patience:100,workers:0,
    lr0:.01,lrf:.01,momentum:.937,weight_decay:.0005,warmup_epochs:3,
    close_mosaic:10,mosaic:1,mixup:0,hsv_h:.015,hsv_s:.7,hsv_v:.4,degrees:0,translate:.1,scale:.5,shear:0,perspective:0,flipud:0,fliplr:.5,
    cache:'False',pretrained:true,amp:true,rect:false,cos_lr:false,freeze:0,multi_scale:0,save_period:-1,seed:0,deterministic:true,
    eval_interval:10,eval_metric:'map50',continue_threshold:.65,stop_threshold:.90,val_max_samples:100,auto_supplement:false,supplement_count:50
  }}
  window.cfg425=cfg425;
  function target425(){return (state.targets||[]).find(x=>x.id===document.getElementById('tr425Target')?.value)}
  function trainAlgCfg425(){const t=target425();return (t?.algorithms||[]).find(x=>x.key===document.getElementById('tr425TrainAlg')?.value)}
  function initSel425(){state.train425Selected={train:new Set((state.images||[]).filter(x=>(x.split||'unassigned')==='train'&&x.annotated).map(x=>x.id)),val:new Set((state.images||[]).filter(x=>(x.split||'unassigned')==='val'&&x.annotated).map(x=>x.id))}}
  function selected425(s){return [...(state.train425Selected?.[s]||new Set())]}
  function labelSummary425(s){const ids=new Set(selected425(s)),labs=new Set();(state.images||[]).filter(x=>ids.has(x.id)).forEach(x=>(x.labels||[]).forEach(l=>labs.add(l)));return [...labs].join('、')||'-'}
  function targetName425(t){const fw=t?.framework==='paddle'?'PaddleDetection':'Ultralytics / YOLO';return `${fw} · ${t?.name||'-'}`}
  function usableTargets425(){return (state.targets||[]).filter(x=>x.status==='ready')}

  window.openTrain424=window.openTrain425=function(aid=''){
    state.train425Config=cfg425();initSel425();
    const algs=state.algorithms||[], preset=algs.find(x=>x.id===aid)||algs[0], targets=usableTargets425();
    modal('创建训练任务',`<div class="train425-create">
      <section class="train425-block"><div class="train425-block-title"><b>1. 训练方式</b></div><div class="form three">
        <div class="field"><label>训练资源 / 框架</label><select id="tr425Target" class="select" onchange="trainResource425()">${targets.map(t=>`<option value="${t.id}">${esc(targetName425(t))}</option>`).join('')||'<option value="">暂无可用训练资源</option>'}</select></div>
        <div class="field"><label>训练算法</label><select id="tr425TrainAlg" class="select" onchange="trainAlgorithm425()"></select></div>
        <div class="field"><label>关联算法</label><select id="tr425AssetAlg" class="select">${algs.map(a=>`<option value="${a.id}" ${a.id===preset?.id?'selected':''}>${esc(a.name)}</option>`).join('')}</select></div>
      </div></section>
      <section class="train425-block"><div class="train425-block-title"><b>2. 训练数据</b><span>训练集更新权重；试验集只用于训练过程验证与质量门禁</span></div>
        <div class="train424-data"><div class="train424-data-card"><div class="row between"><div><b>训练集</b><span id="tr425TrainCount"></span></div><div class="row"><button class="btn mini" onclick="openTrainDataPicker425('train')">选择数据</button><button class="btn mini" onclick="trainDataQuality425('train')">数据质量</button></div></div><div class="train424-selection"><span>包含标签</span><b id="tr425TrainLabels">-</b></div></div>
        <div class="train424-data-card"><div class="row between"><div><b>试验集</b><span id="tr425ValCount"></span></div><div class="row"><button class="btn mini" onclick="openTrainDataPicker425('val')">选择数据</button><button class="btn mini" onclick="trainDataQuality425('val')">数据质量</button></div></div><div class="train424-selection"><span>包含标签</span><b id="tr425ValLabels">-</b></div></div></div>
      </section>
      <section class="train425-block"><div class="row between"><div class="train425-block-title"><b>3. 训练配置</b><span>默认配置可直接训练；需要时再进入配置设置</span></div><button class="btn" onclick="openTrainSettings425()">配置设置</button></div>
        <div class="train425-summary"><div><span>基础模型</span><b id="tr425Model">-</b></div><div><span>Epoch</span><b id="tr425Epoch">100</b></div><div><span>图片尺寸</span><b id="tr425Img">640</b></div><div><span>Batch</span><b id="tr425Batch">8</b></div><div><span>阶段检查</span><b id="tr425Gate">每10轮</b></div></div>
      </section>
      <div id="tr425Estimate" class="estimate424"></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="submitTrain425()">开始训练</button></div>
    </div>`,true);
    setTimeout(()=>{trainResource425();trainCounts425()},20)
  };
  window.startAlgorithmTraining423=function(id){window.setPage?.('训练任务');setTimeout(()=>{if(state.page==='训练任务')openTrain425(id)},30)};

  window.trainResource425=function(){
    const t=target425(), sel=document.getElementById('tr425TrainAlg');if(!sel)return;
    sel.innerHTML=(t?.algorithms||[]).map(a=>`<option value="${esc(a.key)}">${esc(a.name||a.short_name||a.key)}</option>`).join('')||'<option value="">当前资源没有可训练算法</option>';
    const c=state.train425Config||cfg425();c.device=t?.type==='server'?'0':(t?.recommendation?.device||'cpu');state.train425Config=c;trainAlgorithm425()
  };
  window.trainAlgorithm425=function(){
    const a=trainAlgCfg425(), t=target425(), c=state.train425Config||cfg425();
    if(a){c.model=a.base_model||c.model||'';c.epochs=a.default_epochs||c.epochs;c.imgsz=a.default_imgsz||c.imgsz;c.batch=a.default_batch||c.batch}
    if(!c.model){const m=(t?.base_models||[])[0];c.model=m?.value||m?.label||''}
    state.train425Config=c;refreshTrain425()
  };
  function refreshTrain425(){const c=state.train425Config||cfg425();[['tr425Model',String(c.model||'-').split(/[\\/]/).pop()],['tr425Epoch',c.epochs],['tr425Img',c.imgsz],['tr425Batch',c.batch],['tr425Gate',c.eval_interval>0?`每${c.eval_interval}轮 / ${c.val_max_samples||'全部'}张`:'关闭']].forEach(([id,v])=>{const e=document.getElementById(id);if(e)e.textContent=v});trainCounts425()}
  window.trainCounts425=function(){const tr=selected425('train').length,va=selected425('val').length;const a=document.getElementById('tr425TrainCount'),b=document.getElementById('tr425ValCount');if(a)a.textContent=`${tr} 张`;if(b)b.textContent=`${va} 张`;const al=document.getElementById('tr425TrainLabels'),bl=document.getElementById('tr425ValLabels');if(al)al.textContent=labelSummary425('train');if(bl)bl.textContent=labelSummary425('val');const out=document.getElementById('tr425Estimate'),hist=(state.jobs||[]).filter(j=>['done','finished','completed'].includes(j.status)&&j.elapsed_seconds&&j.epochs);if(out){if(hist.length&&tr){const per=hist.map(j=>j.elapsed_seconds/Math.max(1,j.epochs)/Math.max(1,j.dataset_counts?.train||tr)),sec=per.reduce((s,x)=>s+x,0)/per.length*tr*(state.train425Config?.epochs||100);out.innerHTML=`预计训练时间 <b>${fmtTime424(sec)}</b> · 任务开始后按实际 Epoch 速度动态修正`;}else out.textContent='训练开始后将根据实际 Epoch 速度计算预计完成时间'}};

  function pickerImages425(){const split=state.train425PickerSplit,q=(document.getElementById('tp425Q')?.value||'').trim().toLowerCase(),fs=state.train425FilterLabels||new Set();return (state.images||[]).filter(x=>(x.split||'unassigned')===split&&x.annotated&&(!q||String(x.filename||'').toLowerCase().includes(q))&&[...fs].every(l=>(x.labels||[]).includes(l)))}
  window.togglePickerLabel425=function(l){state.train425FilterLabels=state.train425FilterLabels||new Set();state.train425FilterLabels.has(l)?state.train425FilterLabels.delete(l):state.train425FilterLabels.add(l);renderPicker425()};
  window.renderPicker425=function(){const rows=pickerImages425(),draft=state.train425PickerDraft||new Set(),box=document.getElementById('tp425Cards');if(box)box.innerHTML=rows.map(x=>`<label class="train425-thumb ${draft.has(x.id)?'selected':''}"><input type="checkbox" ${draft.has(x.id)?'checked':''} onchange="togglePickerImage425('${x.id}',this.checked)"><img src="${x.url}" loading="lazy"><div class="train425-thumb-body"><b title="${esc(x.filename)}">${esc(x.filename)}</b><div>${(x.labels||[]).map(l=>`<span>${esc(l)}</span>`).join('')}</div><small>${fmtSize424(x.size_bytes)}</small></div></label>`).join('')||'<div class="empty">没有同时包含所选标签的数据</div>';const n=document.getElementById('tp425Count');if(n)n.textContent=`已选 ${draft.size} 张 · 当前 ${rows.length} 张`;const chips=document.getElementById('tp425Labels');if(chips)chips.innerHTML=(state.labels||[]).map(l=>`<button class="${state.train425FilterLabels?.has(l.code)?'on':''}" onclick="togglePickerLabel425('${esc(l.code)}')">${esc(l.display_name||l.code)}</button>`).join('')};
  window.togglePickerImage425=function(id,on){on?state.train425PickerDraft.add(id):state.train425PickerDraft.delete(id);renderPicker425()};
  window.selectPickerVisible425=function(on){pickerImages425().forEach(x=>on?state.train425PickerDraft.add(x.id):state.train425PickerDraft.delete(x.id));renderPicker425()};
  window.openTrainDataPicker425=function(split){state.train425PickerSplit=split;state.train425PickerDraft=new Set(selected425(split));state.train425FilterLabels=new Set();modal(`${split==='train'?'训练集':'试验集'} · 选择数据`,`<div class="trainpicker425"><div class="train425-filter-head"><div><b>标签筛选</b><span>可多选；多选时只显示同时包含这些标签的数据</span></div><div id="tp425Labels" class="train425-filter-chips"></div></div><div class="row train425-picker-tools"><input id="tp425Q" class="input" placeholder="搜索图片名称" oninput="renderPicker425()"><button class="btn" onclick="selectPickerVisible425(true)">全选当前</button><button class="btn" onclick="selectPickerVisible425(false)">取消当前</button><span id="tp425Count"></span></div><div id="tp425Cards" class="train425-thumb-grid"></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="applyPicker425()">确定</button></div></div>`,true);setTimeout(renderPicker425,20)};
  window.applyPicker425=function(){state.train425Selected[state.train425PickerSplit]=new Set(state.train425PickerDraft);closeModal();trainCounts425()};
  window.trainDataQuality425=async function(split){const ids=selected425(split);if(!ids.length)return toast(`请先选择${split==='train'?'训练集':'试验集'}数据`);try{const r=await api(`/api/v44/projects/${pid()}/data-quality`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({split,image_ids:ids})}),q=r.quality||{};modal(`${split==='train'?'训练集':'试验集'} · 数据质量`,`<div class="qualitypopup425"><div class="qualitypopup424-score"><b>${q.overall_score||0}</b><span>综合质量</span></div>${radar424(q.scores||{})}<div class="quality424-facts"><div><span>图片</span><b>${q.images||0}</b></div><div><span>已标注</span><b>${q.annotated_images||0}</b></div><div><span>标签</span><b>${q.label_count||0}</b></div><div><span>标注框</span><b>${q.box_count||0}</b></div><div><span>重复</span><b>${q.duplicate_images||0}</b></div><div><span>低分辨率</span><b>${q.low_resolution||0}</b></div><div><span>无效框</span><b>${q.invalid_boxes||0}</b></div><div><span>容量</span><b>${fmtSize424(q.total_size_bytes)}</b></div></div></div><div class="report425-labeldist">${Object.entries(q.label_boxes||{}).filter(([,v])=>v>0).sort((a,b)=>b[1]-a[1]).map(([l,v])=>`<span><b>${esc(l)}</b><em>${v} 框</em></span>`).join('')}</div>`,true)}catch(e){toast(e.message||e)}};

  function num425(id,def=0){const e=document.getElementById(id);return e?Number(e.value||def):def}
  function chk425(id,def=false){const e=document.getElementById(id);return e?e.checked:def}
  window.openTrainSettings425=function(){const c=state.train425Config||cfg425(),t=target425(),models=t?.base_models||[];modal('训练配置设置',`<div class="train425-settings">
    <section><h3>基础与训练控制</h3><div class="form three"><div class="field"><label>基础模型</label><select id="ts425Model" class="select">${models.map(m=>`<option value="${esc(m.value||m.label)}" ${(m.value||m.label)===c.model?'selected':''}>${esc(m.label||m.value)}</option>`).join('')||`<option value="${esc(c.model)}">${esc(c.model||'-')}</option>`}</select></div><div class="field"><label>Epoch</label><input id="ts425Epochs" class="input" type="number" min="1" value="${c.epochs}"></div><div class="field"><label>图片尺寸 imgsz</label><input id="ts425Size" class="input" type="number" min="32" value="${c.imgsz}"></div><div class="field"><label>Batch</label><input id="ts425Batch" class="input" type="number" value="${c.batch}"></div><div class="field"><label>Early Stop patience</label><input id="ts425Patience" class="input" type="number" min="0" value="${c.patience}"></div><div class="field"><label>Workers</label><input id="ts425Workers" class="input" type="number" min="0" value="${c.workers}"></div><div class="field"><label>保存Checkpoint间隔</label><input id="ts425SavePeriod" class="input" type="number" value="${c.save_period}"></div><div class="field"><label>随机种子</label><input id="ts425Seed" class="input" type="number" value="${c.seed}"></div><div class="field"><label>缓存</label><select id="ts425Cache" class="select"><option value="False" ${c.cache==='False'?'selected':''}>关闭</option><option value="ram" ${c.cache==='ram'?'selected':''}>内存</option><option value="disk" ${c.cache==='disk'?'selected':''}>磁盘</option></select></div></div><div class="train425-checks"><label><input id="ts425Pretrained" type="checkbox" ${c.pretrained?'checked':''}>预训练权重</label><label><input id="ts425Amp" type="checkbox" ${c.amp?'checked':''}>AMP混合精度</label><label><input id="ts425Det" type="checkbox" ${c.deterministic?'checked':''}>确定性训练</label><label><input id="ts425Rect" type="checkbox" ${c.rect?'checked':''}>Rect</label><label><input id="ts425Cos" type="checkbox" ${c.cos_lr?'checked':''}>Cosine LR</label></div></section>
    <section><h3>优化器与学习率</h3><div class="form three"><div class="field"><label>Optimizer</label><select id="ts425Opt" class="select">${['auto','SGD','Adam','AdamW','NAdam','RAdam','RMSProp'].map(x=>`<option ${c.optimizer===x?'selected':''}>${x}</option>`).join('')}</select></div><div class="field"><label>初始学习率 lr0</label><input id="ts425Lr0" class="input" type="number" step="0.0001" value="${c.lr0}"></div><div class="field"><label>最终学习率比例 lrf</label><input id="ts425Lrf" class="input" type="number" step="0.001" value="${c.lrf}"></div><div class="field"><label>Momentum</label><input id="ts425Momentum" class="input" type="number" step="0.001" value="${c.momentum}"></div><div class="field"><label>Weight Decay</label><input id="ts425WD" class="input" type="number" step="0.0001" value="${c.weight_decay}"></div><div class="field"><label>Warmup Epochs</label><input id="ts425Warmup" class="input" type="number" step="0.1" value="${c.warmup_epochs}"></div><div class="field"><label>冻结前N层</label><input id="ts425Freeze" class="input" type="number" min="0" value="${c.freeze}"></div><div class="field"><label>多尺度幅度</label><input id="ts425Multi" class="input" type="number" min="0" max="1" step="0.05" value="${c.multi_scale}"></div></div></section>
    <section><h3>数据增强</h3><div class="form four"><div class="field"><label>Mosaic</label><input id="ts425Mosaic" class="input" type="number" step="0.05" value="${c.mosaic}"></div><div class="field"><label>MixUp</label><input id="ts425Mixup" class="input" type="number" step="0.05" value="${c.mixup}"></div><div class="field"><label>最后N轮关闭Mosaic</label><input id="ts425CloseMosaic" class="input" type="number" value="${c.close_mosaic}"></div><div class="field"><label>HSV-H</label><input id="ts425HsvH" class="input" type="number" step="0.001" value="${c.hsv_h}"></div><div class="field"><label>HSV-S</label><input id="ts425HsvS" class="input" type="number" step="0.05" value="${c.hsv_s}"></div><div class="field"><label>HSV-V</label><input id="ts425HsvV" class="input" type="number" step="0.05" value="${c.hsv_v}"></div><div class="field"><label>旋转 degrees</label><input id="ts425Degrees" class="input" type="number" value="${c.degrees}"></div><div class="field"><label>平移 translate</label><input id="ts425Translate" class="input" type="number" step="0.05" value="${c.translate}"></div><div class="field"><label>缩放 scale</label><input id="ts425Scale" class="input" type="number" step="0.05" value="${c.scale}"></div><div class="field"><label>剪切 shear</label><input id="ts425Shear" class="input" type="number" value="${c.shear}"></div><div class="field"><label>透视 perspective</label><input id="ts425Perspective" class="input" type="number" step="0.001" value="${c.perspective}"></div><div class="field"><label>上下翻转</label><input id="ts425Flipud" class="input" type="number" step="0.05" value="${c.flipud}"></div><div class="field"><label>左右翻转</label><input id="ts425Fliplr" class="input" type="number" step="0.05" value="${c.fliplr}"></div></div></section>
    <section class="train425-gate"><h3>阶段试验与自动优化</h3><div class="form three"><div class="field"><label>每第 N 轮检查</label><input id="ts425EvalInt" class="input" type="number" min="0" value="${c.eval_interval}"></div><div class="field"><label>每次固定抽取试验集</label><input id="ts425ValMax" class="input" type="number" min="0" value="${c.val_max_samples}"><small>0=使用全部；创建任务时固定随机抽样，后续不变化</small></div><div class="field"><label>门禁指标</label><select id="ts425Metric" class="select"><option value="map50" ${c.eval_metric==='map50'?'selected':''}>mAP50</option><option value="recall" ${c.eval_metric==='recall'?'selected':''}>Recall</option><option value="precision" ${c.eval_metric==='precision'?'selected':''}>Precision</option></select></div><div class="field"><label>低于此值停止并优化</label><input id="ts425Continue" class="input" type="number" min="0" max="1" step="0.01" value="${c.continue_threshold}"></div><div class="field"><label>达到此值提前完成</label><input id="ts425Stop" class="input" type="number" min="0" max="1" step="0.01" value="${c.stop_threshold}"></div><div class="field"><label>弱标签补样数量</label><input id="ts425Supplement" class="input" type="number" min="0" value="${c.supplement_count}"></div></div><div class="train425-checks"><label><input id="ts425AutoSupplement" type="checkbox" ${c.auto_supplement?'checked':''}>报告识别弱标签后允许从未处理区补充同标签数据</label></div><div class="train425-gate-flow"><span>训练</span><i>→</i><span>每N轮读取试验指标</span><i>→</i><span>低于下限：停止优化</span><i>→</i><span>中间区间：继续</span><i>→</i><span>达到目标：提前完成</span></div></section>
    <div class="row end sticky-actions425"><button class="btn" onclick="closeModal()">取消</button><button class="btn soft" onclick="state.train425Config=cfg425();closeModal();refreshTrain425();toast('已恢复默认配置')">恢复默认</button><button class="btn primary" onclick="saveTrainSettings425()">保存配置</button></div>
  </div>`,true)};
  window.saveTrainSettings425=function(){const c=state.train425Config||cfg425();Object.assign(c,{model:document.getElementById('ts425Model')?.value||c.model,epochs:num425('ts425Epochs',100),imgsz:num425('ts425Size',640),batch:num425('ts425Batch',8),patience:num425('ts425Patience',100),workers:num425('ts425Workers',0),save_period:num425('ts425SavePeriod',-1),seed:num425('ts425Seed',0),cache:document.getElementById('ts425Cache')?.value||'False',pretrained:chk425('ts425Pretrained',true),amp:chk425('ts425Amp',true),deterministic:chk425('ts425Det',true),rect:chk425('ts425Rect'),cos_lr:chk425('ts425Cos'),optimizer:document.getElementById('ts425Opt')?.value||'auto',lr0:num425('ts425Lr0',.01),lrf:num425('ts425Lrf',.01),momentum:num425('ts425Momentum',.937),weight_decay:num425('ts425WD',.0005),warmup_epochs:num425('ts425Warmup',3),freeze:num425('ts425Freeze',0),multi_scale:num425('ts425Multi',0),mosaic:num425('ts425Mosaic',1),mixup:num425('ts425Mixup',0),close_mosaic:num425('ts425CloseMosaic',10),hsv_h:num425('ts425HsvH',.015),hsv_s:num425('ts425HsvS',.7),hsv_v:num425('ts425HsvV',.4),degrees:num425('ts425Degrees',0),translate:num425('ts425Translate',.1),scale:num425('ts425Scale',.5),shear:num425('ts425Shear',0),perspective:num425('ts425Perspective',0),flipud:num425('ts425Flipud',0),fliplr:num425('ts425Fliplr',.5),eval_interval:num425('ts425EvalInt',0),val_max_samples:num425('ts425ValMax',0),eval_metric:document.getElementById('ts425Metric')?.value||'map50',continue_threshold:num425('ts425Continue',0),stop_threshold:num425('ts425Stop',0),supplement_count:num425('ts425Supplement',0),auto_supplement:chk425('ts425AutoSupplement')});if(c.continue_threshold&&c.stop_threshold&&c.continue_threshold>=c.stop_threshold)return toast('继续训练下限必须小于提前完成阈值');state.train425Config=c;closeModal();refreshTrain425();toast('训练配置已保存')};

  
  function outcome425(j,m,weak){const map=Number(m['metrics/mAP50(B)']||0),rec=Number(m['metrics/recall(B)']||0);if(j.training_outcome==='needs_optimization'||map<.7||rec<.7)return{cls:'bad',title:'本次训练需要继续优化',text:`当前模型在试验集上的效果偏低${weak.length?'，主要薄弱标签为 '+weak.join('、'):''}。优先检查漏检/误检样本，并补充对应场景数据。`};if(j.training_outcome==='target_reached'||(map>=.9&&rec>=.9))return{cls:'good',title:'本次训练效果较好',text:'核心指标已达到较高水平，可以进入最终评测集验证；正式上线前仍建议关注误报、漏报和实际场景稳定性。'};return{cls:'mid',title:'本次训练已完成，可继续针对性优化',text:`整体指标已经具备参考价值${weak.length?'，建议优先优化 '+weak.join('、'):''}。是否发布应再结合最终评测集和业务误报/漏报要求。`}}
  function line425(rows,key,title,pct=true){const vals=rows.map(r=>r[key]).filter(v=>v!=null);if(vals.length<2)return`<div class="report425-chart-empty">暂无${title}曲线</div>`;const W=560,H=170,pad=24,min=pct?0:Math.min(...vals),max=pct?1:Math.max(...vals),den=Math.max(.000001,max-min),pts=rows.map((r,i)=>{const v=r[key];if(v==null)return null;return[pad+i*(W-pad*2)/Math.max(1,rows.length-1),H-pad-(v-min)/den*(H-pad*2)]}).filter(Boolean);return`<div class="report425-chart"><div class="report425-chart-title">${title}</div><svg viewBox="0 0 ${W} ${H}"><line x1="${pad}" y1="${H-pad}" x2="${W-pad}" y2="${H-pad}"/><polyline points="${pts.map(p=>p.join(',')).join(' ')}"/></svg><div class="report425-chart-foot"><span>Epoch 1</span><span>Epoch ${rows.at(-1)?.epoch||rows.length}</span></div></div>`}
  function metricExplain425(name,v){if(v==null)return'-';const n=Number(v);if(name==='Precision')return n>=.9?'误报控制优秀':n>=.8?'误报控制较好':'误报偏多';if(name==='Recall')return n>=.9?'漏检控制优秀':n>=.8?'漏检控制较好':'漏检偏多';if(name==='mAP50')return n>=.9?'整体检测能力优秀':n>=.8?'整体效果较好':'整体效果需提升';return n>=.7?'严格标准下表现较好':'严格标准下仍有提升空间'}
  function aiResultText425(x){if(x.error)return`失败：${esc(x.error)}`;const r=x.result||{};if(typeof r==='string')return esc(r);if(r.cause||r.data_suggestion)return`${esc(r.cause||'')} ${r.data_suggestion?`· 建议：${esc(r.data_suggestion)}`:''}`;if(r.raw)return esc(String(r.raw).slice(0,300));return esc(JSON.stringify(r).slice(0,300))}
  window.trainingReport424=window.trainingReport425=async function(id){try{const r=await api(`/api/v44/projects/${pid()}/jobs/${id}/report`),j=r.job||{},rep=r.report||{},m=rep.metrics||{},pcs=(rep.per_class||[]).slice().sort((a,b)=>(a.recall??2)-(b.recall??2)),weak=rep.weak_labels||[],con=outcome425(j,m,weak),hist=rep.history||[],ds=rep.data_summary||{},cfg=rep.configuration||{},errors=(rep.error_samples||[]).filter(x=>!x.analysis_error),ai=rep.ai_error_analysis||{};const metricCards=[['Precision','metrics/precision(B)','预测出来的目标，有多少是真的'],['Recall','metrics/recall(B)','真实目标，有多少被找出来'],['mAP50','metrics/mAP50(B)','常用综合检测能力'],['mAP50-95','metrics/mAP50-95(B)','更严格定位标准下的综合能力']].map(([n,k,sub])=>`<div><span>${n}</span><b>${pct424(m[k])}</b><em>${esc(metricExplain425(n,m[k]))}</em><small>${sub}</small></div>`).join('');const errHtml=errors.slice(0,40).map(e=>{const im=(state.images||[]).find(x=>x.filename===e.image);return`<div class="report425-error"><div class="report425-error-img">${im?`<img src="${im.url}">`:'<span>无预览</span>'}</div><div><b>${esc(e.image)}</b><span class="fn">漏检 ${e.false_negative_count||0} · ${esc((e.false_negative_labels||[]).join('、')||'-')}</span><span class="fp">误检 ${e.false_positive_count||0} · ${esc((e.false_positive_labels||[]).join('、')||'-')}</span></div></div>`}).join('')||'<div class="empty">未发现错误样本，或当前任务尚未生成逐图分析</div>';
    modal('训练报告',`<div class="report425"><section class="report425-hero ${con.cls}"><div><span>训练结论</span><h2>${con.title}</h2><p>${esc(con.text)}</p></div><div class="report425-hero-side"><span>关联算法</span><b>${esc(j.asset_algorithm_name||'-')}</b><span>训练算法</span><b>${esc(j.algorithm_name||'-')}</b><span>耗时</span><b>${esc(j.elapsed_text||'-')}</b></div></section>
      <section class="report425-metrics">${metricCards}</section>
      <div class="report425-grid"><section class="report425-panel"><div class="report425-title"><b>训练过程</b><span>看模型是不是持续变好，而不是只看最后一个数字</span></div>${line425(hist,'map50','mAP50变化')}${line425(hist,'box_loss','训练 Box Loss',false)}</section><section class="report425-panel"><div class="report425-title"><b>本次训练概况</b></div><div class="report425-facts"><div><span>训练图片</span><b>${ds.counts?.train||0}</b></div><div><span>试验图片</span><b>${ds.counts?.val||0}</b></div><div><span>训练框</span><b>${ds.counts?.train_boxes||0}</b></div><div><span>试验框</span><b>${ds.counts?.val_boxes||0}</b></div><div><span>Epoch</span><b>${cfg.epochs||j.epochs||'-'}</b></div><div><span>基础模型</span><b title="${esc(cfg.model||'')}">${esc(String(cfg.model||'-').split(/[\\/]/).pop())}</b></div></div><div class="report425-gate-summary"><b>阶段质量门禁</b><span>${ds.quality_gate?.eval_interval?`每 ${ds.quality_gate.eval_interval} 轮检查一次 · 固定试验样本 ${ds.quality_gate.stage_eval_samples||'全部'} 张 · 指标 ${esc(ds.quality_gate.metric||'mAP50')}`:'未启用'}</span>${rep.quality_gate_reason?`<em>${esc(rep.quality_gate_reason)}</em>`:''}</div></section></div>
      <section class="report425-panel"><div class="report425-title"><b>各标签表现</b><span>优先看 Recall 低的标签，它们通常意味着漏检更多</span></div><div class="report425-label-table"><table class="table"><thead><tr><th>标签</th><th>Precision</th><th>Recall</th><th>mAP50</th><th>判断</th></tr></thead><tbody>${pcs.map(x=>`<tr><td><b>${esc(x.label)}</b>${weak.includes(x.label)?'<span class="weak425">弱标签</span>':''}</td><td>${pct424(x.precision)}</td><td>${pct424(x.recall)}</td><td>${pct424(x.map50)}</td><td>${x.recall!=null&&x.recall<.75?'漏检偏多':x.precision!=null&&x.precision<.75?'误报偏多':'表现正常'}</td></tr>`).join('')||'<tr><td colspan="5">暂无逐标签指标</td></tr>'}</tbody></table></div></section>
      <section class="report425-panel"><div class="report425-title row between"><div><b>错误样本</b><span>是否答错由人工标注 Ground Truth + 类别 + IoU 客观计算</span></div><div class="row">${weak.length&&j.quality_gate?.auto_supplement?`<button class="btn" onclick="supplementTrain424('${id}')">补充弱标签数据</button>`:''}${(state.modelConfigs||[]).length?`<button class="btn primary" onclick="openAiCause425('${id}')">模型辅助分析原因</button>`:''}</div></div><div class="report425-errors">${errHtml}</div></section>
      ${ai.items?.length?`<section class="report425-panel"><div class="report425-title"><b>模型辅助错误归因</b><span>${esc(ai.model_name||'视觉模型')}只解释“为什么可能错”，不负责判定对错</span></div><div class="report425-ai">${ai.items.map(x=>`<div><b>${esc(x.image)}</b><span>${aiResultText425(x)}</span></div>`).join('')}</div></section>`:''}
      <section class="report425-panel"><details><summary>查看本次训练配置</summary><div class="report425-config">${Object.entries(cfg).map(([k,v])=>`<div><span>${esc(k)}</span><b>${esc(String(v))}</b></div>`).join('')}</div></details></section>
    </div>`,true)}catch(e){toast(e.message||e)}};
  window.openAiCause425=function(id){const opts=(state.modelConfigs||[]).map(c=>`<option value="${c.id}">${esc(c.name)}${c.model_kind==='vlm'?' · VLM':''}</option>`).join('');modal('模型辅助错误归因',`<div class="form"><div class="field"><label>选择视觉模型</label><select id="ai425Model" class="select">${opts}</select></div><div class="field"><label>分析样本数量</label><input id="ai425Limit" class="input" type="number" min="1" max="30" value="12"></div><div class="alert soft">模型不会重新判定“检测对不对”。对错由预测结果与人工标准标注计算；模型只分析小目标、遮挡、夜间、模糊、相似干扰等可能原因。</div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="runAiCause425('${id}')">开始分析</button></div>`,true)};
  window.runAiCause425=async function(id){const mid=document.getElementById('ai425Model')?.value;if(!mid)return toast('请选择模型');try{await api(`/api/v45/projects/${pid()}/jobs/${id}/error-cause-analysis`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model_config_id:mid,limit:num425('ai425Limit',12)})});closeModal();closeModal();trainingReport425(id);toast('模型辅助归因已完成')}catch(e){toast(e.message||e)}};

  function rowsTrain425(){return (state.jobs||[]).map(j=>`<tbody class="trainjob424"><tr onclick="toggleTrain424('${j.id}')"><td><b>${esc(j.asset_algorithm_name||j.algorithm_name||j.id)}</b><div class="muted-line">${esc(j.id)}</div></td><td>${status423(j.status)}</td><td>${esc(j.framework==='paddle'?'PaddleDetection':'Ultralytics / YOLO')}<div class="muted-line">${esc(j.algorithm_name||'')}</div></td><td>训练 ${j.dataset_counts?.train||0} · 试验 ${j.dataset_counts?.val||0}</td><td>${renderJobProgress(j)}</td><td>${fmtTime424(j.eta_seconds)}</td><td>${esc(String(j.created_at||'').slice(0,19))}</td><td onclick="event.stopPropagation()"><div class="row"><button class="btn mini" onclick="showTrainLog423('${j.id}')">日志</button>${['done','finished','completed'].includes(j.status)?`<button class="btn mini primary" onclick="trainingReport425('${j.id}')">训练报告</button>`:''}${['queued','running'].includes(j.status)?`<button class="btn mini danger" onclick="stopJob423('${j.id}')">停止</button>`:''}</div></td></tr>${state.train424Expanded?.[j.id]?`<tr class="trainjob424-output"><td colspan="8"><div class="trainoutput424"><div><span>关联算法</span><b>${esc(j.asset_algorithm_name||'-')}</b></div><div><span>训练成果</span><b>${(j.models||[]).length?j.models.map(x=>`<span class="artifact424">${esc(String(x).split(/[\\/]/).pop())}</span>`).join(' '):'-'}</b></div><div><span>结论</span><b>${esc(j.training_outcome==='target_reached'?'达到目标提前完成':j.training_outcome==='needs_optimization'?'需要优化':j.message||'-')}</b></div></div></td></tr>`:''}</tbody>`).join('')||'<tbody><tr><td colspan="8">暂无训练任务</td></tr></tbody>'}
  window.renderTraining424=window.renderTraining425=function(){document.getElementById('view').innerHTML=`<section class="taskpage424"><div class="taskpage424-head"><div></div><button class="btn primary" onclick="openTrain425()">▶ 开始训练</button></div><section class="panel"><div class="table-wrap"><table class="table train424-table"><thead><tr><th>训练任务</th><th>状态</th><th>训练资源 / 算法</th><th>数据</th><th>进度 / 已用</th><th>预计剩余</th><th>创建时间</th><th>操作</th></tr></thead>${rowsTrain425()}</table></div></section></section>`};

  // version badge
})();


/* ============================================================
   v42.6 — data gallery, fast loading, executive logs, durable cache
   ============================================================ */
var pct424 = window.pct424 = window.pct424 || function(v){if(v==null||isNaN(Number(v)))return '-';const n=Number(v);return(n<=1?n*100:n).toFixed(1)+'%'};
var fmtSize424 = window.fmtSize424 = window.fmtSize424 || function(n){n=Number(n||0);if(n<1024)return n+' B';if(n<1024**2)return(n/1024).toFixed(1)+' KB';if(n<1024**3)return(n/1024**2).toFixed(1)+' MB';return(n/1024**3).toFixed(2)+' GB'};
var fmtTime424 = window.fmtTime424 = window.fmtTime424 || function(sec){sec=Number(sec||0);if(!sec)return '-';if(sec<60)return Math.round(sec)+'秒';if(sec<3600)return Math.floor(sec/60)+'分'+Math.round(sec%60)+'秒';return Math.floor(sec/3600)+'小时'+Math.round(sec%3600/60)+'分'};
var splitName424 = window.splitName424 = window.splitName424 || function(s){return({unassigned:'未处理',train:'训练集',val:'试验集',test:'评测集'})[s]||'未处理'};
var status423 = window.status423 = window.status423 || function(s){const n={queued:'排队中',running:'训练中',done:'已完成',finished:'已完成',completed:'已完成',failed:'失败',stopped:'已停止',ready:'正常',unchecked:'未检测',disabled:'已停用'};const c=['done','finished','completed','ready'].includes(s)?'ok':s==='failed'?'err':'warn';return`<span class="pill ${c}">${esc(n[s]||s||'-')}</span>`};
var taskStatus424 = window.taskStatus424 = window.taskStatus424 || function(t){const s=t?.status||'',c=['done','finished','completed','ready'].includes(s)?'ok':s==='failed'?'err':'warn';return`<span class="pill ${c}">${esc(t?.status_text||s||'-')}</span>`};
var radar424 = window.radar424 = window.radar424 || function(scores,cls=''){const e=Object.entries(scores||{});if(!e.length)return'';const cx=150,cy=142,R=96,n=e.length,pts=r=>e.map((_,i)=>{const a=-Math.PI/2+i*2*Math.PI/n;return`${cx+Math.cos(a)*r},${cy+Math.sin(a)*r}`}).join(' ');const value=e.map(([k,v],i)=>{const a=-Math.PI/2+i*2*Math.PI/n,r=R*Math.max(0,Math.min(100,Number(v||0)))/100;return`${cx+Math.cos(a)*r},${cy+Math.sin(a)*r}`}).join(' ');const labels=e.map(([k,v],i)=>{const a=-Math.PI/2+i*2*Math.PI/n,x=cx+Math.cos(a)*(R+25),y=cy+Math.sin(a)*(R+25);return`<text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="middle">${esc(k)} ${Number(v||0).toFixed(0)}</text>`}).join('');return`<svg class="radar424 ${cls}" viewBox="0 0 300 285">${[.25,.5,.75,1].map(x=>`<polygon points="${pts(R*x)}" class="radar-grid424"/>`).join('')}<polygon points="${value}" class="radar-value424"/>${labels}</svg>`};

(()=>{
  const V426='42.24.0';
  state.data426Labels=state.data426Labels||new Set();
  state.data426Page=state.data426Page||1; state.data426PageSize=48;
  state.data426DeleteMode=false; state.data426MoveMode=false;

  // Faster loading: independent resources are requested concurrently.
  loadRelated=async function(){
    if(!state.project)return; const id=state.project.id; const quiet=p=>p.catch(()=>null);
    let [info,dsets,images,labels,algs,pending,testModels,modelCfg,prompts]=await Promise.all([
      quiet(api(`/api/projects/${id}`)),quiet(api(`/api/projects/${id}/datasets`)),quiet(api(`/api/projects/${id}/images`)),
      quiet(api(`/api/v12/projects/${id}/labels`)),quiet(api(`/api/v12/projects/${id}/algorithms`)),quiet(api(`/api/v12/projects/${id}/publish/pending`)),quiet(api(`/api/v12/projects/${id}/test_models`)),quiet(api('/api/v35/model-configs')),quiet(api('/api/v35/prompt-templates'))
    ]);
    if(info){state.project=info.project;state.jobs=info.jobs||[];state.models=info.models||[]}
    state.datasets=dsets?.items||[];
    if(!state.datasets.length){await quiet(api(`/api/projects/${id}/datasets`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'默认数据集',description:'',kind:'mixed'})}));state.datasets=(await quiet(api(`/api/projects/${id}/datasets`)))?.items||[]}
    state.datasetId='default'; state.images=images||[]; state.labels=labels?.items||[]; state.algorithms=algs?.items||[]; state.pending=pending?.items||[]; state.testModels=testModels?.items||[]; state.modelConfigs=modelCfg?.items||[]; state.promptTemplates=prompts?.items||[];
  };
  loadAll=async function(){
    await ensureWorkspace(); if(!state.project)return; const id=state.project.id,quiet=p=>p.catch(()=>null);
    const [_,opts,infer,rec,local]=await Promise.all([loadRelated(),quiet(api(`/api/training_options?project_id=${id}`)),quiet(api('/api/v16/inference_envs')),quiet(api('/api/system/recommendation')),quiet(api('/api/local_models'))]);
    state.targets=opts?.targets||[];state.inferenceEnvs=infer?.items||[];state.rec=rec;state.localModels=local?.items||[];
  };

  // Replace all native file selectors with platform-styled controls.
  function beautifyFileInputs426(root=document){
    root.querySelectorAll?.('input[type=file]:not([data-file426])').forEach(input=>{
      if(input.dataset.pretty426)return; input.dataset.pretty426='1'; input.classList.add('native-file426');
      const wrap=document.createElement('span');wrap.className='filepicker426';
      const btn=document.createElement('button');btn.type='button';btn.className='btn filepicker426-btn';
      const accept=String(input.getAttribute('accept')||'').toLowerCase();btn.textContent=accept.includes('video')?'＋ 上传视频文件':accept.includes('image')?'＋ 选择图片':'＋ 选择本地文件';
      const name=document.createElement('span');name.className='filepicker426-name';name.textContent='未选择';
      btn.onclick=()=>input.click(); input.addEventListener('change',()=>{const fs=[...(input.files||[])];name.textContent=fs.length?(fs.length===1?fs[0].name:`已选择 ${fs.length} 个文件`):'未选择'});
      input.insertAdjacentElement('afterend',wrap);wrap.append(btn,name);
    });
  }
  window.beautifyFileInputs426=beautifyFileInputs426;



  // Annotation save: update the exact current image immediately; no full reload.
  window.saveAnn=async function(silent=false){
    if(!state.activeImage||!state.ann)return;
    try{const r=await api(`/api/projects/${pid()}/annotations/${state.activeImage.id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({boxes:state.ann.boxes||[]})});state.ann=r?.annotation||state.ann;if(!Array.isArray(state.ann.boxes))state.ann.boxes=[];const img=(state.images||[]).find(x=>x.id===state.activeImage.id);if(img){img.box_count=state.ann.boxes.length;img.annotated=state.ann.boxes.length>0;img.labels=[...new Set(state.ann.boxes.map(b=>b.label).filter(Boolean))];state.activeImage=img}state.annDirty=false;const e=document.getElementById('annSaveState');if(e)e.textContent=`已保存（${state.ann.boxes.length}框）`;drawBoxes();renderAnnSide();if(!silent)toast(`标注已保存：${state.ann.boxes.length}个框`)}catch(e){toast(`保存失败：${e.message||e}`)}
  };

  // ---------------- Dataset gallery ----------------
  function dataMatch426(){
    const tab=state.data424Tab||'unassigned',q=(document.getElementById('data426Q')?.value||'').trim().toLowerCase(),labs=[...state.data426Labels],ann=document.getElementById('data426Ann')?.value||'all';
    return(state.images||[]).filter(x=>{if((x.split||'unassigned')!==tab)return false;if(q&&!String(x.filename||'').toLowerCase().includes(q))return false;if(ann==='marked'&&!x.annotated)return false;if(ann==='unmarked'&&x.annotated)return false;return labs.every(l=>(x.labels||[]).includes(l))});
  }
  window.dataMatch426=dataMatch426;
  function dataCard426(x){const choosing=state.data426DeleteMode||state.data426MoveMode,sel=state.data424Selected?.has(x.id);return`<article class="data426-card ${sel?'selected':''}"><div class="data426-pic" onclick="previewData426('${x.id}')"><img src="${x.url}" loading="lazy" decoding="async"><span class="data426-split">${splitName424(x.split||'unassigned')}</span>${choosing?`<label class="data426-check" onclick="event.stopPropagation()"><input type="checkbox" ${sel?'checked':''} onchange="selectData426('${x.id}',this.checked)"><i></i></label>`:''}</div><div class="data426-body"><div class="data426-title" title="${esc(x.filename)}">${esc(x.filename)}</div><div class="data426-meta"><span>${fmtSize424(x.size_bytes)}</span><span>${x.annotated?'已标注':'未标注'}</span><span>${esc(String(x.created_at||'').slice(0,10))}</span></div><div class="data426-tags">${(x.labels||[]).map(l=>`<span>${esc(l)}</span>`).join('')||'<em>无标签</em>'}</div><div class="data426-actions"><button class="btn mini" onclick="dataDetail424('${x.id}')">详情</button><button class="btn mini primary" onclick="openAnnotation('${x.id}')">标注</button></div></div></article>`}
  window.toggleDataLabel426=function(l){if(l==='__clear__')state.data426Labels.clear();else state.data426Labels.has(l)?state.data426Labels.delete(l):state.data426Labels.add(l);state.data426Page=1;renderDatasets424()};
  window.setDataTab424=function(t){state.data424Tab=t;state.data424Selected.clear();state.data426DeleteMode=false;state.data426MoveMode=false;state.data426Page=1;renderDatasets424()};
  window.selectData426=function(id,on){on?state.data424Selected.add(id):state.data424Selected.delete(id);renderDataCards426()};
  window.renderDataCards426=function(){const box=document.getElementById('data426Grid');if(!box)return;const all=dataMatch426(),pages=Math.max(1,Math.ceil(all.length/state.data426PageSize));state.data426Page=Math.min(state.data426Page,pages);const start=(state.data426Page-1)*state.data426PageSize,rows=all.slice(start,start+state.data426PageSize);box.innerHTML=rows.map(dataCard426).join('')||'<div class="empty data426-empty">当前筛选条件下没有图片</div>';const n=document.getElementById('data426Count');if(n)n.textContent=`${all.length} 张`;const s=document.getElementById('data426SelectedCount');if(s)s.textContent=`已选 ${state.data424Selected.size} 张`;const p=document.getElementById('data426Pager');if(p)p.innerHTML=`<button class="btn mini" ${state.data426Page<=1?'disabled':''} onclick="dataPage426(-1)">上一页</button><span>${state.data426Page} / ${pages}</span><button class="btn mini" ${state.data426Page>=pages?'disabled':''} onclick="dataPage426(1)">下一页</button>`};
  window.dataPage426=function(d){state.data426Page=Math.max(1,state.data426Page+d);renderDataCards426()};
  window.renderDatasets424=function(){
    const counts={unassigned:0,train:0,val:0,test:0};(state.images||[]).forEach(x=>counts[(x.split||'unassigned') in counts?(x.split||'unassigned'):'unassigned']++);
    const chips=(state.labels||[]).map(l=>`<button class="data426-chip ${state.data426Labels.has(l.code)?'on':''}" onclick="toggleDataLabel426('${esc(l.code)}')">${esc(l.display_name||l.code)}</button>`).join('');
    document.getElementById('view').innerHTML=`<section class="data426-shell"><div class="data426-head"><div class="data424-tabs">${[['未处理','unassigned'],['训练集','train'],['试验集','val'],['评测集','test']].map(([n,k])=>`<button class="${state.data424Tab===k?'on':''}" onclick="setDataTab424('${k}')"><span>${n}</span><b>${counts[k]}</b></button>`).join('')}</div><div class="row"><button class="btn primary" onclick="openDataUpload426()">上传</button><button class="btn" onclick="toggleMove426()">调整归属</button><button class="btn danger" onclick="toggleDelete426()">${state.data426DeleteMode?'取消删除':'删除'}</button></div></div><section class="panel data426-panel"><div class="data426-filtertop"><div class="data426-filter-title"><b>标签筛选</b><span>可多选；筛选同时包含所选标签的图片</span></div><div class="data426-chips"><button class="data426-chip clear ${state.data426Labels.size?'':'on'}" onclick="toggleDataLabel426('__clear__')">全部</button>${chips}</div></div><div class="data426-toolbar"><input id="data426Q" class="input" placeholder="搜索图片名称" oninput="state.data426Page=1;renderDataCards426()"><select id="data426Ann" class="select" onchange="state.data426Page=1;renderDataCards426()"><option value="all">全部标注状态</option><option value="marked">已标注</option><option value="unmarked">未标注</option></select><span id="data426Count"></span>${state.data426DeleteMode||state.data426MoveMode?`<b id="data426SelectedCount">已选 ${state.data424Selected.size} 张</b>`:''}${state.data426DeleteMode?'<button class="btn danger" onclick="batchDelete426()">删除已选</button>':''}${state.data426MoveMode?`<select id="data426Move" class="select"><option value="">移动到...</option><option value="unassigned">未处理</option><option value="train">训练集</option><option value="val">试验集</option><option value="test">评测集</option></select><button class="btn primary" onclick="batchMove426()">确定移动</button>`:''}</div><div id="data426Grid" class="data426-grid"></div><div id="data426Pager" class="data426-pager"></div></section></section>`;renderDataCards426();
  };
  window.toggleDelete426=function(){state.data426DeleteMode=!state.data426DeleteMode;state.data426MoveMode=false;state.data424Selected.clear();renderDatasets424()};
  window.toggleMove426=function(){state.data426MoveMode=!state.data426MoveMode;state.data426DeleteMode=false;state.data424Selected.clear();renderDatasets424()};
  window.batchDelete426=async function(){const ids=[...state.data424Selected];if(!ids.length)return toast('请选择要删除的图片');if(!confirm(`确认删除已选 ${ids.length} 张图片？`))return;try{await api(`/api/v46/projects/${pid()}/images/batch-delete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:ids})});state.images=state.images.filter(x=>!state.data424Selected.has(x.id));state.data424Selected.clear();state.data426DeleteMode=false;renderDatasets424();toast(`已删除 ${ids.length} 张`)}catch(e){toast(e.message||e)}};
  window.batchMove426=async function(){const ids=[...state.data424Selected],sp=document.getElementById('data426Move')?.value;if(!ids.length)return toast('请选择图片');if(!sp)return toast('请选择目标归属');try{await api(`/api/v20/projects/${pid()}/images/batch_split`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:ids,split:sp,scope:'selected'})});(state.images||[]).forEach(x=>{if(state.data424Selected.has(x.id))x.split=sp});state.data424Selected.clear();state.data426MoveMode=false;renderDatasets424();toast('数据归属已更新')}catch(e){toast(e.message||e)}};

  window.openDataUpload426=function(){modal('上传数据',`<div class="upload426-choices"><button onclick="chooseUploadImages426()"><b>上传图片</b><span>支持 JPG、PNG、WEBP，可一次选择多张</span></button><button onclick="chooseUploadZip426()"><b>上传文件</b><span>上传 ZIP，自动解压并识别 YOLO / COCO / VOC 等数据</span></button></div><input id="up426Images" data-file426="1" class="hidden-file426" type="file" accept="image/*" multiple onchange="doUploadImages426(this)"><input id="up426Zip" data-file426="1" class="hidden-file426" type="file" accept=".zip,application/zip" onchange="doUploadZip426(this)">`,true)};
  window.chooseUploadImages426=()=>document.getElementById('up426Images')?.click();window.chooseUploadZip426=()=>document.getElementById('up426Zip')?.click();
  window.doUploadImages426=async function(inp){const fs=[...(inp.files||[])];if(!fs.length)return;const fd=new FormData();fs.forEach(f=>fd.append('files',f));fd.append('dataset_id','default');try{await api(`/api/projects/${pid()}/images`,{method:'POST',body:fd});closeModal();await loadRelated();renderDatasets424();toast(`已上传 ${fs.length} 张图片`)}catch(e){toast(e.message||e)}};
  window.doUploadZip426=async function(inp){const f=inp.files?.[0];if(!f)return;const fd=new FormData();fd.append('file',f);try{const r=await api(`/api/v18/projects/${pid()}/datasets/default/import`,{method:'POST',body:fd});closeModal();await loadRelated();renderDatasets424();toast(`导入完成：${r.imported_images||0} 张图片`)}catch(e){toast(e.message||e)}};

  function previewBody426(){const list=state.data426PreviewList||[],i=state.data426PreviewIndex||0,x=list[i];if(!x)return'';return`<div class="data426-preview"><div class="data426-preview-image"><img src="${x.url}"></div><aside><b title="${esc(x.filename)}">${esc(x.filename)}</b><div><span>大小</span><strong>${fmtSize424(x.size_bytes)}</strong></div><div><span>尺寸</span><strong>${x.width||'-'} × ${x.height||'-'}</strong></div><div><span>标注</span><strong>${x.annotated?'已标注':'未标注'}</strong></div><div><span>标签</span><strong>${esc((x.labels||[]).join('、')||'-')}</strong></div><div><span>归属</span><strong>${splitName424(x.split||'unassigned')}</strong></div><div class="row"><button class="btn" ${i<=0?'disabled':''} onclick="previewStep426(-1)">上一张</button><button class="btn" ${i>=list.length-1?'disabled':''} onclick="previewStep426(1)">下一张</button><button class="btn primary" onclick="openAnnotation('${x.id}')">标注</button></div></aside></div>`}
  window.previewData426=function(id){const list=dataMatch426(),idx=list.findIndex(x=>x.id===id);if(idx<0)return;state.data426PreviewList=list;state.data426PreviewIndex=idx;modal('图片预览',previewBody426(),true)};
  window.previewStep426=function(d){const list=state.data426PreviewList||[];if(!list.length)return;state.data426PreviewIndex=Math.max(0,Math.min(list.length-1,(state.data426PreviewIndex||0)+d));const layers=[...document.querySelectorAll('.v424-modal-layer')],top=layers[layers.length-1],body=top?.querySelector('.modal-body')||document.getElementById('modalBody');if(body)window.ModalContentRuntime.replace(body,previewBody426())};

  // ---------------- Boss-friendly training log ----------------
  function metricFromLog426(txt,name){const patterns={map50:/mAP50[^0-9]*([0-9.]+)/ig,precision:/precision[^0-9]*([0-9.]+)/ig,recall:/recall[^0-9]*([0-9.]+)/ig};let m,last=null,re=patterns[name];if(!re)return null;while((m=re.exec(txt||'')))last=Number(m[1]);return last}
  window.showTrainLog423=async function(id){const j=(state.jobs||[]).find(x=>x.id===id)||{},txt=await safe(api(`/api/projects/${pid()}/jobs/${id}/log`))||'',p=Number(j.progress_percent||0),ep=j.current_epoch||0,total=j.total_epochs||j.epochs||0,map=j.metrics?.map50??metricFromLog426(txt,'map50'),pr=j.metrics?.precision??metricFromLog426(txt,'precision'),re=j.metrics?.recall??metricFromLog426(txt,'recall');let conclusion='任务已创建，正在准备训练。';if(j.status==='running')conclusion=p<20?'模型正在学习基础特征，当前指标波动属于正常。':p<70?'训练进入主要学习阶段，重点看效果是否持续提升。':'已进入训练后段，重点观察效果是否稳定以及是否接近目标。';if(['done','finished','completed'].includes(j.status))conclusion='训练已完成，可查看训练报告判断是否进入正式评测或继续优化。';if(j.status==='failed')conclusion='训练失败，需要查看下方技术详情中的失败原因后重新执行。';modal('训练进展',`<div class="bosslog426"><div class="bosslog426-hero"><div><span>当前状态</span><b>${esc(j.status==='running'?'训练中':j.status==='done'||j.status==='finished'?'已完成':j.status==='failed'?'失败':statusName(j.status))}</b></div><div><span>整体进度</span><b>${p.toFixed(0)}%</b></div><div><span>训练轮次</span><b>${ep}/${total||'-'}</b></div><div><span>已用时间</span><b>${fmtTime424(j.elapsed_seconds)}</b></div><div><span>预计剩余</span><b>${fmtTime424(j.eta_seconds)}</b></div></div><div class="bosslog426-progress"><i style="width:${Math.max(0,Math.min(100,p))}%"></i></div><section><h3>现在怎么看？</h3><p>${conclusion}</p></section><div class="bosslog426-metrics"><div><span>当前 mAP50</span><b>${map==null?'-':pct424(map)}</b><em>整体检测效果</em></div><div><span>Precision</span><b>${pr==null?'-':pct424(pr)}</b><em>报出来的结果有多少是真的</em></div><div><span>Recall</span><b>${re==null?'-':pct424(re)}</b><em>真实目标有多少被找到了</em></div></div><details class="bosslog426-tech"><summary>查看技术训练日志</summary><pre class="log train423-log">${esc(txt||'暂无日志')}</pre></details><div class="row end"><button class="btn" onclick="refreshTrainLog426('${id}')">刷新</button><button class="btn" onclick="closeModal()">关闭</button></div></div>`,true)};
  window.refreshTrainLog426=async function(id){await loadRelated();closeModal();showTrainLog423(id)};

  // ---------------- Local / cloud model config ----------------
  function promptTable426(){const list=state.promptTemplates||[];return`<table class="table"><thead><tr><th>名称</th><th>框架</th><th>标签</th><th>保存格式</th><th>操作</th></tr></thead><tbody>${list.map(t=>`<tr><td><b>${esc(t.name)}</b></td><td>${esc(t.framework||'common')}</td><td>${esc((t.labels||[]).join('、'))}</td><td>${esc(t.save_format||'internal')}</td><td><button class="btn mini" onclick="openPromptTemplateModalV35('${t.id}')">编辑</button><button class="btn mini danger" onclick="deletePromptTemplateV35('${t.id}')">删除</button></td></tr>`).join('')||'<tr><td colspan="5">暂无提示词模板</td></tr>'}</tbody></table>`}
  window.renderModelConfigPageV35=function(){const cs=state.modelConfigs||[],rows=cs.map(c=>`<tr><td><b>${esc(c.name)}</b><div class="muted-line">${esc(c.model_name||'')}</div></td><td><span class="pill ${c.provider_type==='cloud'?'blue':'ok'}">${c.provider_type==='cloud'?'云端模型':'本机模型'}</span></td><td>${esc(c.detect_url||'-')}</td><td><button class="btn mini" onclick="testModelConfigV35('${c.id}')">测试</button><button class="btn mini" onclick="openModelConfigModalV35('${c.id}')">编辑</button><button class="btn mini danger" onclick="deleteModelConfigV35('${c.id}')">删除</button></td></tr>`).join('');document.getElementById('view').innerHTML=`<section class="panel"><div class="panel-head"><div class="panel-title">模型配置</div><button class="btn primary" onclick="openModelConfigModalV35()">新增模型</button></div><div class="panel-body"><table class="table"><thead><tr><th>模型</th><th>位置</th><th>接口</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="4">暂无模型配置</td></tr>'}</tbody></table></div></section><section class="panel"><div class="panel-head"><div class="panel-title">模型标注库</div><button class="btn primary" onclick="openPromptTemplateModalV35()">新增提示词</button></div><div class="panel-body">${promptTable426()}</div></section>`};
  window.openModelConfigModalV35=function(id=''){const c=(state.modelConfigs||[]).find(x=>x.id===id)||{},provider=c.provider_type||'local',local=state.localModels||[],defModel=c.model_name||(provider==='local'?(local[0]?.name||local[0]?.filename||local[0]?.path||''):'');modal(id?'编辑模型配置':'新增模型配置',`<div class="model426"><div class="model426-switch"><button id="mc426Local" class="${provider!=='cloud'?'on':''}" onclick="switchModelProvider426('local')">本机模型</button><button id="mc426Cloud" class="${provider==='cloud'?'on':''}" onclick="switchModelProvider426('cloud')">云端模型</button></div><div class="form two"><input id="mcProvider" type="hidden" value="${provider}"><div class="field"><label>配置名称</label><input id="mcName" class="input" value="${esc(c.name||'')}"></div><div class="field"><label>模型名称</label><input id="mcModel" class="input" list="mc426LocalModels" value="${esc(defModel)}"><datalist id="mc426LocalModels">${local.map(m=>`<option value="${esc(m.name||m.filename||m.path||'')}">`).join('')}</datalist></div><div class="field full"><label id="mc426UrlLabel">${provider==='cloud'?'云端模型接口':'本机模型服务地址'}</label><input id="mcUrl" class="input" value="${esc(c.detect_url||c.base_url||(provider==='cloud'?'':'http://127.0.0.1:9000/detect'))}"></div><div id="mc426ApiWrap" class="field ${provider==='cloud'?'':'hidden'}"><label>API Key</label><input id="mcApiKey" class="input" type="password" placeholder="留空保持原值"></div><div class="field"><label>健康检查地址</label><input id="mcHealth" class="input" value="${esc(c.health_url||'')}"></div><div class="field"><label>请求方式</label><select id="mcMode" class="select"><option value="json_base64" ${c.request_mode!=='multipart_file'?'selected':''}>JSON Base64</option><option value="multipart_file" ${c.request_mode==='multipart_file'?'selected':''}>Multipart 文件</option></select></div><div class="field"><label>图片字段</label><input id="mcImageField" class="input" value="${esc(c.image_field||'image')}"></div><div class="field"><label>提示词字段</label><input id="mcPromptField" class="input" value="${esc(c.prompt_field||'prompt')}"></div><div class="field full"><label>备注</label><input id="mcRemark" class="input" value="${esc(c.remark||'')}"></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveModelConfig426('${id}')">保存</button></div></div>`,true)};
  window.switchModelProvider426=function(p){document.getElementById('mcProvider').value=p;document.getElementById('mc426Local')?.classList.toggle('on',p==='local');document.getElementById('mc426Cloud')?.classList.toggle('on',p==='cloud');document.getElementById('mc426ApiWrap')?.classList.toggle('hidden',p!=='cloud');const lab=document.getElementById('mc426UrlLabel'),url=document.getElementById('mcUrl'),model=document.getElementById('mcModel');if(lab)lab.textContent=p==='cloud'?'云端模型接口':'本机模型服务地址';if(p==='local'){if(url&&!url.value)url.value='http://127.0.0.1:9000/detect';if(model&&!model.value){const m=(state.localModels||[])[0];model.value=m?.name||m?.filename||m?.path||''}}else{if(url&&url.value.startsWith('http://127.0.0.1'))url.value='';if(model)model.value=''}};
  window.saveModelConfig426=async function(id=''){const provider=document.getElementById('mcProvider')?.value||'local',name=document.getElementById('mcName')?.value.trim(),model=document.getElementById('mcModel')?.value.trim(),url=document.getElementById('mcUrl')?.value.trim()||(provider==='local'?'http://127.0.0.1:9000/detect':'');if(!name)return toast('请输入配置名称');if(!model)return toast('请输入模型名称');if(provider==='cloud'&&!url)return toast('云端模型必须填写真实接口地址');const body={name,provider_type:provider,detect_url:url,health_url:document.getElementById('mcHealth')?.value.trim()||'',model_name:model,request_mode:document.getElementById('mcMode')?.value||'json_base64',image_field:document.getElementById('mcImageField')?.value||'image',prompt_field:document.getElementById('mcPromptField')?.value||'prompt',api_key:document.getElementById('mcApiKey')?.value||'',remark:document.getElementById('mcRemark')?.value||'',model_kind:'vision_detect'};try{await api(id?`/api/v35/model-configs/${id}`:'/api/v35/model-configs',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeModal();await loadRelated();renderModelConfigPageV35();toast('模型配置已保存')}catch(e){toast(e.message||e)}};

  // Version deployment result cache also persists until user explicitly refreshes.
  window.showVersionDeployments423=async function(aid,vid,force=false){const key=`cl_deploy_version_${pid()}_${aid}_${vid}`;let r=null;if(!force){try{r=JSON.parse(localStorage.getItem(key)||'null')?.data||null}catch(e){}}if(!r){try{r=await api(`/api/v42/projects/${pid()}/algorithms/${aid}/versions/${vid}/deployments`);localStorage.setItem(key,JSON.stringify({ts:Date.now(),data:r}))}catch(e){return toast(e.message||e)}}const v=r.version||{},items=r.items||[];modal(`${r.algorithm?.name||'算法'} · ${v.version_name||'版本'} · 部署产物`,`<div class="row between"><div class="deploy423-source"><span>源模型</span><b>${esc(v.model_name||'')}</b><em>${Number(v.size_mb||0).toFixed(2)} MB</em></div><button class="btn" onclick="refreshVersionDeploy426('${aid}','${vid}')">刷新</button></div><div class="deploy423-list">${items.map(j=>`<div class="deploy423-job"><div class="deploy423-job-head"><div><b>${esc(j.target_name||j.target)}</b>${taskStatus424(j)}</div><time>${esc(String(j.finished_at||j.created_at||'').slice(0,19))}</time></div><div class="deploy423-job-meta"><span>转换资源：${esc(j.resource_name||'-')}</span><span>任务：${esc(j.id)}</span></div><div class="deploy423-files">${(j.outputs||[]).map(o=>`<div><span>${esc(o.name)}</span><b>${o.size_mb!=null?Number(o.size_mb).toFixed(2)+' MB':''}</b>${o.download_url?`<a class="btn mini" href="${o.download_url}">下载</a>`:''}</div>`).join('')||'<div>暂无输出文件</div>'}</div></div>`).join('')||'<div class="empty">暂无部署产物</div>'}</div>`,true)};
  window.refreshVersionDeploy426=function(aid,vid){localStorage.removeItem(`cl_deploy_version_${pid()}_${aid}_${vid}`);closeModal();showVersionDeployments423(aid,vid,true)};

  // Final version marker.
  const nav426=renderNav;renderNav=function(){nav426();const e=document.querySelector('.nav-footer b');if(e)e.textContent='v'+V426};
  const top426=renderTop;renderTop=function(){top426();const e=document.getElementById('versionBadge');if(e)e.textContent='v'+V426};
})();

/* ============================================================
   v42.7 — ordinary-user curation + AI-assisted training
   ============================================================ */
(()=>{
  const V427='42.24.0';
  state.v427Advanced = localStorage.getItem('cl_v427_advanced')==='1';
  state.v427OpsTab = state.v427OpsTab || 'label';
  state.v427TaskMinimized = null;
  state.v427UploadIds = state.v427UploadIds || [];

  function status427(s){return ({queued:'排队中',running:'运行中',awaiting_confirmation:'待确认',done:'已完成',failed:'失败',stopped:'已停止'})[s]||s||'-'}
  function pill427(s){return `<span class="pill ${s==='done'?'ok':s==='failed'?'err':s==='awaiting_confirmation'?'blue':'warn'}">${status427(s)}</span>`}
  function fileTime427(x){return esc(String(x||'').replace('T',' ').slice(0,19))}
  function modalBody427(){const layers=[...document.querySelectorAll('.v424-modal-layer')],top=layers.at(-1);return top?.querySelector('.modal-body')||document.getElementById('modalBody')}

  // ----- simpler navigation, advanced deploy/resources hidden by default -----
  window.toggleAdvanced427=function(){state.v427Advanced=!state.v427Advanced;localStorage.setItem('cl_v427_advanced',state.v427Advanced?'1':'0');renderNav()};
  const icon427={工作台:'▦',质量中心:'◇',算法列表:'◆',训练任务:'▶',数据集:'▤',视频切帧:'▣','自动标注及清洗':'✦',测试发布:'✓',检测台:'◎',部署转换:'⇄',部署产物:'▥',模型配置:'◉',训练资源:'▧',部署资源:'⬡'};
  renderNav=function(){
    const groups=[
      {title:'总览',items:['工作台','质量中心']},
      {title:'算法生产',items:['算法列表','训练任务']},
      {title:'数据中心',items:['数据集','视频切帧','自动标注及清洗']},
      {title:'测试评测',items:['测试发布','检测台']},
    ];
    if(state.v427Advanced){groups.push({title:'部署中心',items:['部署转换','部署产物']},{title:'资源配置',items:['模型配置','训练资源','部署资源']})}
    document.getElementById('nav').innerHTML=`<div class="nav-project"><div class="nav-project-k">当前项目</div><div class="nav-project-v">${esc(state.project?.name||'默认空间')}</div></div>${groups.map(g=>`<div class="nav-group"><div class="nav-group-title">${g.title}</div>${g.items.map(n=>`<button class="nav-btn ${state.page===n?'active':''}" onclick="setPage('${n}')"><span class="nav-left"><i>${icon427[n]||'•'}</i><b>${n}</b></span><span class="nav-arrow">›</span></button>`).join('')}</div>`).join('')}<div class="nav-advanced427"><button onclick="toggleAdvanced427()">${state.v427Advanced?'收起高级功能':'展开高级功能'}</button></div><div class="nav-footer"><span>Version</span><b>v${V427}</b></div>`;
  };

  // ----- dataset cards: edit + whole-card selection + compact filter -----
  function matching427(){return dataMatch426?dataMatch426():[]}
  function selectOrPreview427(id){if(state.data426DeleteMode||state.data426MoveMode){const on=!state.data424Selected.has(id);on?state.data424Selected.add(id):state.data424Selected.delete(id);renderDataCards426();return}previewData426(id)}
  window.selectOrPreview427=selectOrPreview427;
  function card427(x){const choosing=state.data426DeleteMode||state.data426MoveMode,sel=state.data424Selected.has(x.id);return`<article class="data426-card data427-card ${sel?'selected':''}" onclick="selectOrPreview427('${x.id}')"><div class="data426-pic"><img src="${x.url}" loading="lazy" decoding="async"><span class="data426-split">${splitName424(x.split||'unassigned')}</span>${choosing?`<label class="data426-check" onclick="event.stopPropagation()"><input type="checkbox" ${sel?'checked':''} onchange="selectData426('${x.id}',this.checked)"><i></i></label>`:''}</div><div class="data426-body"><div class="data426-title" title="${esc(x.filename)}">${esc(x.filename)}</div><div class="data426-meta"><span>${fmtSize424(x.size_bytes)}</span><span>${x.annotated?'已标注':'未标注'}</span><span>${fileTime427(x.created_at).slice(0,10)}</span></div><div class="data426-tags">${(x.labels||[]).map(l=>`<span>${esc(l)}</span>`).join('')||'<em>无标签</em>'}</div><div class="data426-actions" onclick="event.stopPropagation()"><button class="btn mini" onclick="editData427('${x.id}')">编辑</button><button class="btn mini" onclick="dataDetail424('${x.id}')">详情</button><button class="btn mini primary" onclick="openAnnotation('${x.id}')">标注</button></div></div></article>`}
  window.renderDataCards426=function(){const box=document.getElementById('data426Grid');if(!box)return;const all=matching427(),pages=Math.max(1,Math.ceil(all.length/(state.data426PageSize||48)));state.data426Page=Math.max(1,Math.min(state.data426Page||1,pages));const start=(state.data426Page-1)*(state.data426PageSize||48),rows=all.slice(start,start+(state.data426PageSize||48));box.innerHTML=rows.map(card427).join('')||'<div class="empty data426-empty">当前筛选条件下没有图片</div>';const n=document.getElementById('data426Count');if(n)n.textContent=`${all.length} 张`;const s=document.getElementById('data426SelectedCount');if(s)s.textContent=`已选 ${state.data424Selected.size} 张`;const p=document.getElementById('data426Pager');if(p)p.innerHTML=`<button class="btn mini" ${state.data426Page<=1?'disabled':''} onclick="dataPage426(-1)">上一页</button><span>${state.data426Page} / ${pages}</span><button class="btn mini" ${state.data426Page>=pages?'disabled':''} onclick="dataPage426(1)">下一页</button>`};
  window.editData427=function(id){const x=(state.images||[]).find(a=>a.id===id);if(!x)return;modal('编辑数据',`<div class="form"><div class="field"><label>名称</label><input id="data427Name" class="input" value="${esc(x.filename)}"></div><div class="data427-edit-meta"><span>大小 ${fmtSize424(x.size_bytes)}</span><span>${x.width||'-'}×${x.height||'-'}</span><span>${x.annotated?'已标注':'未标注'}</span></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveData427('${id}')">保存</button></div>`,false)};
  window.saveData427=async function(id){const name=document.getElementById('data427Name')?.value.trim();if(!name)return toast('请输入名称');try{const r=await api(`/api/v47/projects/${pid()}/images/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});const i=(state.images||[]).findIndex(x=>x.id===id);if(i>=0)Object.assign(state.images[i],r.image||{});closeModal();renderDatasets424();toast('名称已更新')}catch(e){toast(e.message||e)}};

  const baseRenderDatasets427=window.renderDatasets424;
  window.renderDatasets424=function(){baseRenderDatasets427();const sel=document.getElementById('data426Ann');if(sel)sel.classList.add('compact427');const toolbar=document.querySelector('.data426-toolbar');if(toolbar&&!toolbar.querySelector('.clean-short427'))toolbar.insertAdjacentHTML('beforeend',`<button class="btn clean-short427" onclick="createClean427({image_ids:matching427().map(x=>x.id)})">一键清洗当前筛选</button><button class="btn clean-short427" onclick="createAiLabel427({image_ids:matching427().filter(x=>!x.annotated).map(x=>x.id)})">AI标注当前未标注</button>`)};

  // ----- upload result review -----
  function uploadReview427(ids,title='上传完成'){state.v427UploadIds=ids||[];const rows=(state.images||[]).filter(x=>state.v427UploadIds.includes(x.id));modal(title,`<div class="uploadreview427"><div class="uploadreview427-head"><div><b>已入库 ${rows.length} 张图片</b><span>可以先查看，再清洗或AI标注</span></div><div class="row"><button class="btn" onclick="createClean427({image_ids:state.v427UploadIds})">一键清洗</button><button class="btn primary" onclick="createAiLabel427({image_ids:state.v427UploadIds.filter(id=>!(state.images.find(x=>x.id===id)?.annotated))})">一键AI标注</button></div></div><div class="uploadreview427-grid">${rows.slice(0,120).map(x=>`<button onclick="previewData426('${x.id}')"><img src="${x.url}" loading="lazy"><b>${esc(x.filename)}</b><span>${x.annotated?'已标注':'未标注'} · ${fmtSize424(x.size_bytes)}</span></button>`).join('')||'<div class="empty">没有新增图片</div>'}</div></div>`,true)}
  window.doUploadImages426=async function(inp){const fs=[...(inp.files||[])];if(!fs.length)return;const fd=new FormData();fs.forEach(f=>fd.append('files',f));fd.append('dataset_id','default');try{const r=await api(`/api/projects/${pid()}/images`,{method:'POST',body:fd});closeModal();const uploaded=r.uploaded||[];uploaded.forEach(x=>{x.split=x.split||'unassigned';x.annotated=false;x.labels=[];x.box_count=0});state.images=[...uploaded,...(state.images||[])];renderDatasets424();uploadReview427(uploaded.map(x=>x.id),'图片上传完成')}catch(e){toast(e.message||e)}};
  window.doUploadZip426=async function(inp){const f=inp.files?.[0];if(!f)return;const before=new Set((state.images||[]).map(x=>x.id)),fd=new FormData();fd.append('file',f);try{const r=await api(`/api/v18/projects/${pid()}/datasets/default/import`,{method:'POST',body:fd});closeModal();await loadRelated();renderDatasets424();const ids=(state.images||[]).filter(x=>!before.has(x.id)).map(x=>x.id);uploadReview427(ids,`文件导入完成 · ${r.detected_format||'数据集'}`)}catch(e){toast(e.message||e)}};

  // ----- task minimization -----
  function ensureFloat427(){let e=document.getElementById('v427TaskFloat');if(!e){e=document.createElement('button');e.id='v427TaskFloat';e.className='taskfloat427 hidden';document.body.appendChild(e)}return e}
  function setFloat427(type,id,text){const e=ensureFloat427();state.v427TaskMinimized={type,id};e.classList.remove('hidden');e.innerHTML=`<i></i><span>${esc(text||'后台处理中')}</span>`;e.onclick=()=>{e.classList.add('hidden');showTaskProgress427(type,id)}}
  function clearFloat427(id){if(state.v427TaskMinimized?.id===id){ensureFloat427().classList.add('hidden');state.v427TaskMinimized=null}}
  window.minimizeTask427=function(type,id){setFloat427(type,id,type==='clean'?'正在自动清洗':'正在AI标注');closeModal()};
  async function fetchTask427(type,id){if(type==='clean'){const r=await api(`/api/v47/projects/${pid()}/clean-tasks`);return (r.items||[]).find(x=>x.id===id)}const r=await api(`/api/v33/projects/${pid()}/prelabel-tasks`);return (r.items||[]).find(x=>x.id===id)}
  window.showTaskProgress427=async function(type,id){const t=await safe(fetchTask427(type,id));if(!t)return toast('任务不存在');clearFloat427(id);const done=['awaiting_confirmation','done','failed','stopped'].includes(t.status);modal(type==='clean'?'自动清洗':'AI自动标注',`<div class="wait427"><div class="wait427-anim ${done?'done':''}"><i></i><i></i><i></i><b>${esc(t.status_text||status427(t.status))}</b></div><div class="wait427-progress"><i style="width:${Number(t.progress||0)}%"></i></div><div class="wait427-stats"><span>进度 <b>${t.progress||0}%</b></span><span>已处理 <b>${t.processed_images||0}/${t.total_images||0}</b></span><span>预计剩余 <b>${fmtTime424(t.eta_seconds)}</b></span>${type==='clean'?`<span>发现问题 <b>${t.flagged_images||0}</b></span>`:`<span>候选框 <b>${t.boxes_added||0}</b></span>`}</div>${t.error?`<div class="error-box422">${esc(t.error)}</div>`:''}<div class="row end">${!done?`<button class="btn" onclick="minimizeTask427('${type}','${id}')">最小化</button>`:''}${t.status==='awaiting_confirmation'?`<button class="btn primary" onclick="${type==='clean'?`reviewClean427('${id}')`:`reviewAiLabel427('${id}')`}">查看并确认</button>`:''}<button class="btn" onclick="closeModal()">关闭</button></div></div>`,false);if(!done)setTimeout(async()=>{const now=await safe(fetchTask427(type,id));if(now&&['queued','running'].includes(now.status)){closeModal();showTaskProgress427(type,id)}},1600)};

  // ----- OpenCV cleaning -----
  window.createClean427=function(opts={}){const ids=opts.image_ids||[];modal('创建自动清洗任务',`<div class="clean427-create"><div class="clean427-summary"><b>${ids.length?`处理已选/筛选的 ${ids.length} 张`:'处理全部数据'}</b><span>系统只扫描并给出建议，确认前不会删除任何图片</span></div><div class="clean427-rules"><label><input id="cl427Exact" type="checkbox" checked><b>重复图</b><span>SHA-256 精确重复</span></label><label><input id="cl427Near" type="checkbox" checked><b>近似重复</b><span>感知哈希相似图片</span></label><label><input id="cl427Low" type="checkbox" checked><b>分辨率过低</b><span>低于设定宽高</span></label><label><input id="cl427High" type="checkbox"><b>分辨率过高</b><span>高于设定宽高</span></label><label><input id="cl427Blur" type="checkbox" checked><b>疑似模糊</b><span>OpenCV Laplacian 清晰度</span></label><label><input id="cl427Bright" type="checkbox"><b>过暗 / 过亮</b><span>平均亮度异常</span></label><label><input id="cl427Corrupt" type="checkbox" checked><b>图片损坏</b><span>无法正常解码</span></label></div><details class="advanced427-box"><summary>高级阈值</summary><div class="form three"><div class="field"><label>最小宽度</label><input id="cl427MinW" class="input" value="320"></div><div class="field"><label>最小高度</label><input id="cl427MinH" class="input" value="240"></div><div class="field"><label>模糊阈值</label><input id="cl427BlurV" class="input" value="45"></div><div class="field"><label>最大宽度</label><input id="cl427MaxW" class="input" value="10000"></div><div class="field"><label>最大高度</label><input id="cl427MaxH" class="input" value="10000"></div><div class="field"><label>近似重复距离</label><input id="cl427Ham" class="input" value="5"></div><div class="field"><label>最低亮度</label><input id="cl427BMin" class="input" value="15"></div><div class="field"><label>最高亮度</label><input id="cl427BMax" class="input" value="245"></div></div></details><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick='submitClean427(${JSON.stringify(ids)})'>开始清洗</button></div></div>`,true)};
  window.submitClean427=async function(ids=[]){const body={image_ids:ids,exact_duplicate:!!document.getElementById('cl427Exact')?.checked,near_duplicate:!!document.getElementById('cl427Near')?.checked,near_duplicate_hamming:+document.getElementById('cl427Ham')?.value||5,min_width:document.getElementById('cl427Low')?.checked?(+document.getElementById('cl427MinW')?.value||320):0,min_height:document.getElementById('cl427Low')?.checked?(+document.getElementById('cl427MinH')?.value||240):0,max_width:document.getElementById('cl427High')?.checked?(+document.getElementById('cl427MaxW')?.value||10000):999999,max_height:document.getElementById('cl427High')?.checked?(+document.getElementById('cl427MaxH')?.value||10000):999999,blur_check:!!document.getElementById('cl427Blur')?.checked,blur_min_laplacian:+document.getElementById('cl427BlurV')?.value||45,brightness_check:!!document.getElementById('cl427Bright')?.checked,brightness_min:+document.getElementById('cl427BMin')?.value||15,brightness_max:+document.getElementById('cl427BMax')?.value||245,corrupt_check:!!document.getElementById('cl427Corrupt')?.checked,task_name:`自动清洗-${new Date().toLocaleDateString()}`};try{const t=await api(`/api/v47/projects/${pid()}/clean-tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeModal();showTaskProgress427('clean',t.id)}catch(e){toast(e.message||e)}};
  window.reviewClean427=async function(id){const r=await api(`/api/v47/projects/${pid()}/clean-tasks/${id}/result`),items=r.result?.items||[];state.v427CleanConfirm=new Set(items.filter(x=>x.suggest_delete).map(x=>String(x.image_id)));modal('清洗结果确认',`<div class="review427"><div class="review427-top"><div><b>发现 ${items.length} 张需要关注</b><span>默认勾选建议剔除项；夜间、特殊画质等有业务价值的数据可取消勾选保留</span></div><button class="btn" onclick="toggleAllClean427(${JSON.stringify(items.map(x=>String(x.image_id)))})">全选/全不选</button></div><div class="review427-grid">${items.map(x=>`<label class="review427-card"><input type="checkbox" checked onchange="toggleCleanItem427('${x.image_id}',this.checked)"><img src="${x.url||((state.images||[]).find(i=>i.id===x.image_id)?.url)||''}" loading="lazy"><b>${esc(x.filename||'')}</b><div>${(x.issues||[]).map(y=>`<span>${esc(y.name)} · ${esc(y.detail)}</span>`).join('')}</div></label>`).join('')||'<div class="empty">本次没有发现需要清洗的问题</div>'}</div><div class="row end"><button class="btn" onclick="closeModal()">暂不处理</button><button class="btn primary" onclick="confirmClean427('${id}')">确认应用清洗</button></div></div>`,true)};
  window.toggleCleanItem427=(id,on)=>on?state.v427CleanConfirm.add(String(id)):state.v427CleanConfirm.delete(String(id));
  window.toggleAllClean427=function(ids){const all=ids.every(x=>state.v427CleanConfirm.has(String(x)));ids.forEach(x=>all?state.v427CleanConfirm.delete(String(x)):state.v427CleanConfirm.add(String(x)));document.querySelectorAll('.review427-card input').forEach(x=>x.checked=!all)};
  window.confirmClean427=async function(id){try{const r=await api(`/api/v47/projects/${pid()}/clean-tasks/${id}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delete_ids:[...state.v427CleanConfirm]})});closeModal();await loadRelated();render();toast(`清洗已确认，删除 ${r.deleted||0} 张`)}catch(e){toast(e.message||e)}};

  // ----- AI annotation: labels only, model automatically selected -----
  function refs427(){return (state.images||[]).filter(x=>x.annotated).slice(0,80)}
  window.createAiLabel427=function(opts={}){const ids=opts.image_ids?.length?opts.image_ids:(state.images||[]).filter(x=>!x.annotated&&(x.split||'unassigned')==='unassigned').map(x=>x.id);state.v427AiRef=new Set();const model=(state.modelConfigs||[]).find(x=>x.default_for_annotation)||(state.modelConfigs||[])[0];modal('创建AI自动标注任务',`<div class="ailabel427"><div class="ailabel427-model"><span>系统自动使用</span><b>${esc(model?.name||'未配置AI模型')}</b><em>模型与提示词由“高级功能 → 模型配置”统一维护，普通用户无需选择</em></div><div class="field"><label>要标注的标签</label><input id="ai427Labels" class="input" placeholder="例如：人员、黄色安全帽、烟火（可用顿号分隔）"></div><div class="or427"><i></i><span>或者</span><i></i></div><div class="ref427"><div><b>跟随已有标注</b><span>选择参考图片，系统自动提取这些图片已有的标签，用同一套标签标注未标注图片</span></div><div class="ref427-grid">${refs427().map(x=>`<button onclick="toggleRef427('${x.id}',this)"><img src="${x.url}" loading="lazy"><span>${esc((x.labels||[]).join('、')||'已标注')}</span></button>`).join('')||'<div class="empty">当前还没有已标注图片可作为参考</div>'}</div></div><details class="advanced427-box"><summary>高级设置</summary><div class="form two"><div class="field"><label>置信度阈值</label><input id="ai427Threshold" class="input" value="0.45"></div><div class="field check"><label><input id="ai427Overwrite" type="checkbox"> 覆盖相同标签旧标注</label></div></div></details><div class="ailabel427-target">本次处理 <b>${ids.length}</b> 张图片</div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick='submitAiLabel427(${JSON.stringify(ids)})'>开始AI标注</button></div></div>`,true)};
  window.toggleRef427=function(id,btn){state.v427AiRef.has(id)?state.v427AiRef.delete(id):state.v427AiRef.add(id);btn.classList.toggle('on',state.v427AiRef.has(id))};
  window.submitAiLabel427=async function(ids=[]){if(!ids.length)return toast('没有需要标注的图片');const body={image_ids:ids,labels_text:document.getElementById('ai427Labels')?.value||'',reference_image_ids:[...state.v427AiRef],threshold:+document.getElementById('ai427Threshold')?.value||.45,overwrite:!!document.getElementById('ai427Overwrite')?.checked,task_name:`AI自动标注-${new Date().toLocaleDateString()}`};try{const t=await api(`/api/v47/projects/${pid()}/ai-label-tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeModal();showTaskProgress427('label',t.id)}catch(e){toast(e.message||e)}};
  window.reviewAiLabel427=async function(id){const r=await api(`/api/v47/projects/${pid()}/ai-label-tasks/${id}/result`),items=r.result?.items||[];state.v427AiConfirm=new Set(items.map(x=>String(x.image_id)));modal('AI标注结果确认',`<div class="review427"><div class="review427-top"><div><b>${esc((r.result?.labels||[]).join('、'))}</b><span>AI标注先作为候选结果，确认后才写入正式标注</span></div></div><div class="review427-grid">${items.map(x=>`<label class="review427-card"><input type="checkbox" checked onchange="toggleAiConfirm427('${x.image_id}',this.checked)"><div class="review427-img"><img src="${x.url||((state.images||[]).find(i=>i.id===x.image_id)?.url)||''}" loading="lazy"><i>${(x.boxes||[]).length} 框</i></div><b>${esc(x.filename||'')}</b><div>${[...new Set((x.boxes||[]).map(b=>b.label))].map(y=>`<span>${esc(y)}</span>`).join('')||'<span>未检测到目标</span>'}</div></label>`).join('')}</div><div class="row end"><button class="btn" onclick="closeModal()">暂不应用</button><button class="btn primary" onclick="confirmAiLabel427('${id}')">确认写入标注</button></div></div>`,true)};
  window.toggleAiConfirm427=(id,on)=>on?state.v427AiConfirm.add(String(id)):state.v427AiConfirm.delete(String(id));
  window.confirmAiLabel427=async function(id){try{const r=await api(`/api/v47/projects/${pid()}/ai-label-tasks/${id}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:[...state.v427AiConfirm]})});closeModal();await loadRelated();render();toast(`已确认 ${r.applied_images||0} 张，写入 ${r.boxes_added||0} 个框`)}catch(e){toast(e.message||e)}};

  // ----- combined operation center -----
  async function loadOps427(){const [pl,cl]=await Promise.all([safe(api(`/api/v33/projects/${pid()}/prelabel-tasks`)),safe(api(`/api/v47/projects/${pid()}/clean-tasks`))]);state.prelabel427=pl?.items||[];state.clean427=cl?.items||[]}
  function opProgress427(t){return`<div class="opprog427"><i style="width:${t.progress||0}%"></i></div><span>${t.processed_images||0}/${t.total_images||0}</span>`}
  window.renderOps427=async function(){await loadOps427();const tab=state.v427OpsTab;document.getElementById('view').innerHTML=`<section class="ops427"><div class="ops427-head"><div class="seg"><button class="${tab==='label'?'on':''}" onclick="state.v427OpsTab='label';renderOps427()">AI自动标注</button><button class="${tab==='clean'?'on':''}" onclick="state.v427OpsTab='clean';renderOps427()">自动清洗</button></div><button class="btn primary" onclick="${tab==='label'?'createAiLabel427()':'createClean427()'}">＋ 创建${tab==='label'?'AI标注':'清洗'}任务</button></div><section class="panel"><div class="table-wrap"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>处理进度</th><th>${tab==='label'?'候选框':'问题图片'}</th><th>时间</th><th>操作</th></tr></thead><tbody>${(tab==='label'?state.prelabel427:state.clean427).map(t=>`<tr><td><b>${esc(t.name||t.id)}</b><div class="muted-line">${tab==='label'?esc((t.requested_labels||[t.target_label]).filter(Boolean).join('、')):'OpenCV / 感知哈希'}</div></td><td>${pill427(t.status)}</td><td>${opProgress427(t)}</td><td>${tab==='label'?(t.boxes_added||0):(t.flagged_images||0)}</td><td>${fileTime427(t.created_at)}<div class="muted-line">${fileTime427(t.finished_at||t.finished_scan_at)}</div></td><td><div class="row"><button class="btn mini" onclick="showTaskProgress427('${tab==='label'?'label':'clean'}','${t.id}')">详情</button>${t.status==='awaiting_confirmation'?`<button class="btn mini primary" onclick="${tab==='label'?`reviewAiLabel427('${t.id}')`:`reviewClean427('${t.id}')`}">确认结果</button>`:''}</div></td></tr>`).join('')||'<tr><td colspan="6">暂无任务</td></tr>'}</tbody></table></div></section></section>`;if([...(state.prelabel427||[]),...(state.clean427||[])].some(t=>['queued','running'].includes(t.status)))setTimeout(()=>{if(state.page==='自动标注及清洗')renderOps427()},2200)};

  // ----- model config: prompt lives with model -----
  window.openModelConfigModalV35=function(id=''){const c=(state.modelConfigs||[]).find(x=>x.id===id)||{},provider=c.provider_type||'local',local=state.localModels||[],defModel=c.model_name||(provider==='local'?(local[0]?.name||local[0]?.filename||local[0]?.path||''):'');modal(id?'编辑模型配置':'新增模型配置',`<div class="model426"><div class="model426-switch"><button id="mc426Local" class="${provider!=='cloud'?'on':''}" onclick="switchModelProvider426('local')">本机模型</button><button id="mc426Cloud" class="${provider==='cloud'?'on':''}" onclick="switchModelProvider426('cloud')">云端模型</button></div><div class="form two"><input id="mcProvider" type="hidden" value="${provider}"><div class="field"><label>配置名称</label><input id="mcName" class="input" value="${esc(c.name||'')}"></div><div class="field"><label>模型名称</label><input id="mcModel" class="input" list="mc426LocalModels" value="${esc(defModel)}"><datalist id="mc426LocalModels">${local.map(m=>`<option value="${esc(m.name||m.filename||m.path||'')}">`).join('')}</datalist></div><div class="field full"><label id="mc426UrlLabel">${provider==='cloud'?'云端模型接口':'本机模型服务地址'}</label><input id="mcUrl" class="input" value="${esc(c.detect_url||c.base_url||(provider==='cloud'?'':'http://127.0.0.1:9000/detect'))}"></div><div id="mc426ApiWrap" class="field ${provider==='cloud'?'':'hidden'}"><label>API Key</label><input id="mcApiKey" class="input" type="password" placeholder="留空保持原值"></div><div class="field"><label>请求方式</label><select id="mcMode" class="select"><option value="json_base64" ${c.request_mode!=='multipart_file'?'selected':''}>JSON Base64</option><option value="multipart_file" ${c.request_mode==='multipart_file'?'selected':''}>Multipart 文件</option></select></div><div class="field"><label>健康检查地址</label><input id="mcHealth" class="input" value="${esc(c.health_url||'')}"></div><div class="field"><label>图片字段</label><input id="mcImageField" class="input" value="${esc(c.image_field||'image')}"></div><div class="field"><label>提示词字段</label><input id="mcPromptField" class="input" value="${esc(c.prompt_field||'prompt')}"></div><div class="field full"><label>自动标注提示词模板</label><textarea id="mcAnnPrompt" class="textarea" placeholder="可使用 {labels} 作为标签占位符">${esc(c.annotation_prompt_template||'')}</textarea></div><div class="field full"><label>训练中途AI评判提示词</label><textarea id="mcTrainPrompt" class="textarea">${esc(c.training_intervention_prompt||'')}</textarea></div><div class="field check"><label><input id="mcDefaultAnn" type="checkbox" ${c.default_for_annotation?'checked':''}> 设为默认自动标注模型</label></div><div class="field check"><label><input id="mcDefaultTrain" type="checkbox" ${c.default_for_training_ai?'checked':''}> 设为默认训练介入AI</label></div><div class="field full"><label>备注</label><input id="mcRemark" class="input" value="${esc(c.remark||'')}"></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveModelConfig427('${id}')">保存</button></div></div>`,true)};
  window.saveModelConfig427=async function(id=''){const provider=document.getElementById('mcProvider')?.value||'local',name=document.getElementById('mcName')?.value.trim(),model=document.getElementById('mcModel')?.value.trim(),url=document.getElementById('mcUrl')?.value.trim()||(provider==='local'?'http://127.0.0.1:9000/detect':'');if(!name||!model)return toast('请填写配置名称和模型名称');if(provider==='cloud'&&!url)return toast('云端模型必须填写真实接口地址');const body={name,provider_type:provider,detect_url:url,health_url:document.getElementById('mcHealth')?.value.trim()||'',model_name:model,request_mode:document.getElementById('mcMode')?.value||'json_base64',image_field:document.getElementById('mcImageField')?.value||'image',prompt_field:document.getElementById('mcPromptField')?.value||'prompt',api_key:document.getElementById('mcApiKey')?.value||'',remark:document.getElementById('mcRemark')?.value||'',model_kind:'vision_detect',annotation_prompt_template:document.getElementById('mcAnnPrompt')?.value||'',training_intervention_prompt:document.getElementById('mcTrainPrompt')?.value||'',default_for_annotation:!!document.getElementById('mcDefaultAnn')?.checked,default_for_training_ai:!!document.getElementById('mcDefaultTrain')?.checked};try{await api(id?`/api/v35/model-configs/${id}`:'/api/v35/model-configs',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeModal();await loadRelated();renderModelConfigPageV35();toast('模型配置已保存')}catch(e){toast(e.message||e)}};

  // ----- training config: real AI intervention -----
  const baseCfg427=window.cfg425;
  window.cfg425=function(){return Object.assign(baseCfg427(),{ai_intervention_enabled:false,ai_intervention_epochs:[30,60],ai_model_config_id:'',ai_eval_samples:20,ai_action_mode:'auto',ai_extra_epochs:20,ai_max_rounds:1})};
  const baseOpenSettings427=window.openTrainSettings425;
  window.openTrainSettings425=function(){baseOpenSettings427();requestAnimationFrame(()=>{const body=modalBody427();if(!body||body.querySelector('.ai-train427'))return;const c=state.train425Config||window.cfg425();const actions=body.querySelector('.sticky-actions425')||body.lastElementChild;const models=(state.modelConfigs||[]).map(m=>`<option value="${m.id}" ${c.ai_model_config_id===m.id?'selected':''}>${esc(m.name)}</option>`).join('');actions?.insertAdjacentHTML('beforebegin',`<section class="ai-train427"><div class="row between"><div><b>AI中途介入</b><span>可选功能。程序先用试验集和Ground Truth算真实指标，AI只在限定动作里给训练策略建议。</span></div><label class="switch427"><input id="ai427EnableTrain" type="checkbox" ${c.ai_intervention_enabled?'checked':''}><i></i></label></div><div class="form three"><div class="field"><label>计划总轮数</label><input class="input" value="${c.epochs||100} 轮" readonly></div><div class="field"><label>试验集来源</label><input class="input" value="本任务已选择的试验集 · ${(state.train425Selected?.val||new Set()).size} 张" readonly></div><div class="field"><label>AI介入轮次</label><input id="ai427Epochs" class="input" value="${(c.ai_intervention_epochs||[30,60]).join('、')}" placeholder="例如 30、60"></div><div class="field"><label>介入AI</label><select id="ai427TrainModel" class="select">${models||'<option value="">暂无模型配置</option>'}</select></div><div class="field"><label>每次固定抽取试验集</label><input id="ai427EvalSamples" class="input" type="number" value="${c.ai_eval_samples||20}"></div><div class="field"><label>AI可追加轮数</label><input id="ai427Extra" class="input" type="number" value="${c.ai_extra_epochs||20}"></div><div class="field"><label>最多自动介入次数</label><input id="ai427Rounds" class="input" type="number" min="1" max="5" value="${c.ai_max_rounds||1}"></div><div class="field"><label>执行方式</label><select id="ai427Mode" class="select"><option value="auto" ${c.ai_action_mode!=='advise'?'selected':''}>AI评判后自动执行</option><option value="advise" ${c.ai_action_mode==='advise'?'selected':''}>只给建议，不自动调整</option></select></div></div><div class="ai-train427-flow"><span>到达指定Epoch</span><i>→</i><span>抽试验集并算FP/FN/指标</span><i>→</i><span>AI判断</span><i>→</i><span>继续 / 补同标签新数据并续训 / 追加轮数</span></div></section>`)});};
  const baseSaveSettings427=window.saveTrainSettings425;
  window.saveTrainSettings425=function(){const enabled=!!document.getElementById('ai427EnableTrain')?.checked,epochs=(document.getElementById('ai427Epochs')?.value||'').split(/[、,，;；\s]+/).map(Number).filter(x=>x>0),model=document.getElementById('ai427TrainModel')?.value||'',evalN=+document.getElementById('ai427EvalSamples')?.value||20,extra=+document.getElementById('ai427Extra')?.value||20,rounds=+document.getElementById('ai427Rounds')?.value||1,mode=document.getElementById('ai427Mode')?.value||'auto';if(enabled&&!epochs.length)return toast('开启AI中途介入后，请设置至少一个介入轮次');if(enabled&&!model)return toast('请选择介入AI');baseSaveSettings427();Object.assign(state.train425Config,{ai_intervention_enabled:enabled,ai_intervention_epochs:epochs,ai_model_config_id:model,ai_eval_samples:evalN,ai_extra_epochs:extra,ai_max_rounds:rounds,ai_action_mode:mode})};
  
  // ----- high-end training timeline including AI interventions -----
  window.showTrainLog423=async function(id){const j=(state.jobs||[]).find(x=>x.id===id)||{},txt=await safe(api(`/api/projects/${pid()}/jobs/${id}/log`))||'',p=Number(j.progress_percent||0),ep=j.current_epoch||0,total=j.total_epochs||j.epochs||0,events=j.ai_intervention_events||[],gate=j.gate_events||[];let headline='训练任务正在准备';if(j.status==='running')headline=p<25?'模型正在建立基础识别能力':p<75?'模型进入主要学习阶段':'训练进入收敛阶段';if(['done','finished','completed'].includes(j.status))headline='训练已经完成，可结合报告决定是否进入评测';if(j.status==='failed')headline='训练中断，需要处理失败原因';const timeline=[{title:'任务创建',text:`训练 ${j.dataset_counts?.train||0} 张 · 试验 ${j.dataset_counts?.val||0} 张`,done:true},...gate.map(g=>({title:`阶段检查 · Epoch ${g.epoch}`,text:`${g.metric} ${g.value==null?'-':pct424(g.value)} · ${g.decision||'继续'}`,done:true})),...events.map(e=>({title:`AI介入 · Epoch ${e.epoch}`,text:`${({continue:'继续训练',supplement_and_retrain:'补充数据并续训',extend_epochs:'追加训练轮数',error:'AI调用失败'})[e.action]||e.action} · ${e.reason||''}`,ai:true,done:true}))];if(j.ai_continuation)timeline.push({title:'AI策略执行',text:`${j.ai_continuation.action==='supplement_and_retrain'?`补充 ${j.ai_continuation.supplemented_image_ids?.length||0} 张新训练数据`:'使用原训练数据'} · 追加 ${j.ai_continuation.extra_epochs||0} 轮`,ai:true,done:true});timeline.push({title:['done','finished','completed'].includes(j.status)?'训练完成':'当前训练',text:`Epoch ${ep}/${total||'-'} · ${p.toFixed(0)}%`,current:j.status==='running',done:['done','finished','completed'].includes(j.status)});modal('训练运行中心',`<div class="trainlog427"><section class="trainlog427-hero"><div><span>当前判断</span><h2>${esc(headline)}</h2><p>${j.message?esc(j.message):'平台持续记录训练进度、质量检查和AI介入决策。'}</p></div><div class="trainlog427-kpis"><div><span>整体进度</span><b>${p.toFixed(0)}%</b></div><div><span>轮次</span><b>${ep}/${total||'-'}</b></div><div><span>已用时间</span><b>${fmtTime424(j.elapsed_seconds)}</b></div><div><span>预计剩余</span><b>${fmtTime424(j.eta_seconds)}</b></div></div></section><section class="trainlog427-flow">${timeline.map(x=>`<div class="${x.ai?'ai':''} ${x.current?'current':''}"><i></i><section><b>${esc(x.title)}</b><span>${esc(x.text)}</span></section></div>`).join('')}</section><details class="trainlog427-tech"><summary>工程师技术日志</summary><pre class="log train423-log">${esc(txt||'暂无技术日志')}</pre></details><div class="row end"><button class="btn" onclick="refreshTrainLog426('${id}')">刷新</button><button class="btn" onclick="closeModal()">关闭</button></div></div>`,true)};

  // route + page alias
  const renderBase427=render;
  render=function(){renderNav();renderTop();renderSummary();if(state.page==='自动标注及清洗'){renderOps427();return}renderBase427()};
})();

/* ============================================================
   v42.8 — algorithm-first iteration, queue-only task center,
             timestamp versions and version-level conversions
   ============================================================ */
(()=>{
  const V428='42.24.0';
  const DONE428=new Set(['done','finished','completed','failed','stopped']);
  const ACTIVE428=new Set(['queued','running','paused','waiting','pending']);
  const TARGET_NAMES428={ascend:'华为 Atlas / Ascend OM',rockchip:'瑞芯微 RKNN',sophon:'算能 Sophon / BModel',onnx:'ONNX',tensorrt:'NVIDIA TensorRT',paddle_inference:'Paddle Inference'};
  state.train428Tab=state.train428Tab||'active';
  state.alg428Expanded=state.alg428Expanded||{};

  const dt428=v=>v?String(v).replace('T',' ').replace('Z','').slice(0,19):'-';
  const metricPct428=v=>{if(v==null||v===''||Number.isNaN(Number(v)))return '-';const n=Number(v);return (n<=1?n*100:n).toFixed(1)+'%'};
  window.readTrainingPriority428=function(id){
    const el=document.getElementById(id),priority=Number(el?el.value:50);
    if(!Number.isInteger(priority)||priority<1||priority>999){toast('任务优先级必须是 1~999 的整数，1 为最高优先级');return null}
    return priority;
  };
  const statusText428=s=>({queued:'排队中',running:'训练中',paused:'已暂停',done:'已完成',finished:'已完成',completed:'已完成',failed:'失败',stopped:'已停止',waiting:'等待中',pending:'等待中'})[s]||s||'-';
  const statusPill428=s=>`<span class="pill ${['done','finished','completed'].includes(s)?'ok':s==='failed'?'err':s==='paused'?'blue':'warn'}">${esc(statusText428(s))}</span>`;
  function metricVersion428(v){
    const direct=Number(v?.accuracy);if(Number.isFinite(direct))return direct;
    const rep=v?.report||{};
    const pools=[rep.metrics||{},rep];
    for(const o of pools){for(const [k,val] of Object.entries(o||{})){const kk=String(k).toLowerCase().replace(/\s+/g,'');if(kk.includes('map50')&&!kk.includes('95')){const n=Number(val);if(Number.isFinite(n))return n}}}
    return null;
  }
  function algoMeta428(a){return{type:a?.algorithm_type||'',industry:a?.industry||''}}
  function algTypeName428(id){return({yolo_ultralytics:'YOLO / Ultralytics',paddle_detection:'PaddleDetection',opencv:'OpenCV 传统视觉',mmdetection:'MMDetection',custom_python:'自定义 Python / 其他'})[id]||id||'算法'}
  function algTrainable428(a){return ['yolo_ultralytics','paddle_detection'].includes(algoMeta428(a).type)}
  function resourceName428(j){return j?.execution_resource?.name||j?.execution_resource?.base_url||j?.server_name||j?.server_id||(j?.target==='remote'?'远程训练服务器':'本机训练环境')}
  function gateMetricName428(k){return ({map50:'mAP50',precision:'Precision',recall:'Recall'})[k]||k||'mAP50'}
  function gateDecision428(g){const d=String(g?.decision||'');if(d.includes('target')||d.includes('达标'))return '达到目标，提前完成';if(d.includes('stop')||d.includes('optimization')||d.includes('停止'))return '低于门槛，停止训练';return '通过本次检查，继续训练'}
  function selectedIds428(split){return [...(state.train425Selected?.[split]||new Set())]}
  function selectedLabels428(split){const ids=new Set(selectedIds428(split)),labs=new Set();(state.images||[]).filter(x=>ids.has(x.id)).forEach(x=>(x.labels||[]).forEach(l=>labs.add(l)));return [...labs]}

  // ---------------------- algorithm list / versions ----------------------
  function versionRow428(a,v){
    const acc=metricVersion428(v),canDownload=!!String(v.stored_path||'').trim();
    return `<div class="alg428-version-row">
      <div class="alg428-version-id"><i></i><div><b>${esc(v.version_name||'-')}</b><span>${dt428(v.finished_at||v.created_at)}</span></div></div>
      <div class="alg428-version-status"><span>训练结果</span>${statusPill428(v.training_status||v.status||'done')}</div>
      <div class="alg428-version-accuracy"><span>正确率 · mAP50</span><b>${metricPct428(acc)}</b></div>
      <div class="alg428-version-model"><span>模型成果</span><b>${canDownload?esc(v.model_name||String(v.stored_path).split(/[\\/]/).pop()):'无可用模型产物'}</b></div>
      <div class="alg428-version-actions">
        <button class="btn mini" onclick="event.stopPropagation();showReport('${a.id}','${v.id}')">训练报告</button>
        <button class="btn mini primary" onclick="event.stopPropagation();openVersionConvert428('${a.id}','${v.id}')">转换</button>
        ${canDownload?`<a class="btn mini" onclick="event.stopPropagation()" href="/api/v12/projects/${pid()}/algorithms/${a.id}/versions/${v.id}/download">下载模型</a>`:''}
      </div>
    </div>`;
  }
  function renderAlgCards428(){
    const box=document.getElementById('alg428List');if(!box)return;
    const q=(document.getElementById('alg428Q')?.value||'').trim().toLowerCase(),type=document.getElementById('alg428Type')?.value||'all',industry=document.getElementById('alg428Industry')?.value||'all';
    const rows=(state.algorithms||[]).filter(a=>{const m=algoMeta428(a);return(!q||`${a.name} ${a.remark||''} ${m.industry} ${m.type}`.toLowerCase().includes(q))&&(type==='all'||m.type===type)&&(industry==='all'||m.industry===industry)});
    box.innerHTML=rows.map(a=>{const vers=a.versions||[],latest=vers[0],m=algoMeta428(a),open=!!state.alg428Expanded[a.id],active=(state.jobs||[]).find(j=>j.asset_algorithm_id===a.id&&ACTIVE428.has(j.status));return `<article class="alg428-card ${open?'open':''}">
      <div class="alg428-main" onclick="toggleAlgorithm428('${a.id}')">
        <div class="alg428-logo">${esc((a.name||'算').slice(0,1))}</div>
        <div class="alg428-info"><div class="alg428-title"><b>${esc(a.name)}</b><span>${esc(algTypeName428(m.type))}</span>${m.industry?`<em>${esc(m.industry)}</em>`:''}</div><p>${esc(a.remark||'')}</p><div class="alg428-meta"><span>累计版本 <b>${vers.length}</b></span><span>最新版本 <b>${latest?esc(latest.version_name):'-'}</b></span><span>最新正确率 <b>${metricPct428(metricVersion428(latest))}</b></span></div></div>
        <div class="alg428-state">${active?`<span class="alg428-running">${esc(statusText428(active.status))}</span><small>${esc(resourceName428(active))}</small>`:'<span>可训练</span>'}</div>
        <div class="alg428-actions" onclick="event.stopPropagation()"><button class="btn mini" onclick="viewAlgorithm428('${a.id}')">详情</button><button class="btn mini" onclick="editAlgorithm423('${a.id}')">编辑</button><button class="btn mini primary" ${algTrainable428(a)?`onclick="startAlgorithmTraining423('${a.id}')"`:'disabled'}>训练</button><button class="btn mini danger" onclick="delAlgorithm('${a.id}')">删除</button><i class="alg428-chevron">⌄</i></div>
      </div>
      ${open?`<div class="alg428-versions"><div class="alg428-version-head"><b>迭代版本</b><span>版本号按训练完成时间自动生成</span></div>${vers.length?vers.map(v=>versionRow428(a,v)).join(''):'<div class="empty alg428-empty">还没有训练版本，点击上方“训练”开始第一次迭代</div>'}</div>`:''}
    </article>`}).join('')||'<div class="empty">暂无算法</div>';
  }
  window.toggleAlgorithm428=function(id){state.alg428Expanded[id]=!state.alg428Expanded[id];renderAlgCards428()};
  window.filterAlgorithms428=renderAlgCards428;
  window.renderAlgorithms423=async function(){
    const inds=[...new Set((state.algorithms||[]).map(a=>a.industry).filter(Boolean))].sort();
    document.getElementById('view').innerHTML=`<section class="alg428-shell"><div class="alg428-toolbar"><div class="filter423"><input id="alg428Q" class="input" placeholder="搜索算法" oninput="filterAlgorithms428()"><select id="alg428Industry" class="select" onchange="filterAlgorithms428()"><option value="all">全部行业场景</option>${inds.map(x=>`<option>${esc(x)}</option>`).join('')}</select><select id="alg428Type" class="select" onchange="filterAlgorithms428()"><option value="all">全部算法类型</option><option value="yolo_ultralytics">YOLO / Ultralytics</option><option value="paddle_detection">PaddleDetection</option><option value="opencv">OpenCV 传统视觉</option><option value="mmdetection">MMDetection</option><option value="custom_python">自定义 Python / 其他</option></select></div><button class="btn primary" onclick="openNewAlgorithm423()">＋ 新建算法</button></div><div id="alg428List" class="alg428-list"></div></section>`;
    renderAlgCards428();
  };
  window.viewAlgorithm428=function(id){const a=(state.algorithms||[]).find(x=>x.id===id);if(!a)return;const m=algoMeta428(a),vers=a.versions||[];modal('算法详情',`<div class="alg428-detail"><section><div class="alg428-detail-name"><div class="alg428-logo">${esc((a.name||'算').slice(0,1))}</div><div><h2>${esc(a.name)}</h2><span>${esc(algTypeName428(m.type))}${m.industry?` · ${esc(m.industry)}`:''}</span></div></div><p>${esc(a.remark||'')}</p></section><section><div class="alg428-version-head"><b>版本列表</b><span>${vers.length} 个版本</span></div>${vers.length?vers.map(v=>versionRow428(a,v)).join(''):'<div class="empty">暂无版本</div>'}</section></div>`,true)};

  // ---------------------- version conversion ----------------------
  function cacheKey428(kind,...ids){return`cl_train_v428_${kind}_${pid()}_${ids.join('_')}`}
  function readCache428(k){try{return JSON.parse(localStorage.getItem(k)||'null')}catch(e){return null}}
  function writeCache428(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}
  async function deploymentHistory428(aid,vid,force=false){const k=cacheKey428('verdeploy',aid,vid);if(!force){const c=readCache428(k);if(c)return c}const r=await api(`/api/v42/projects/${pid()}/algorithms/${aid}/versions/${vid}/deployments`);writeCache428(k,r);return r}
  async function deployResources428(force=false){const k=cacheKey428('deployresources');if(!force){const c=readCache428(k);if(c)return c}const r=await api('/api/v39/deploy/resources');writeCache428(k,r);return r}
  function deployOutput428(job){return (job.outputs||[]).map(o=>`<div class="alg428-output"><div><b>${esc(o.name||'-')}</b><span>${o.size_mb!=null?Number(o.size_mb).toFixed(2)+' MB':''}</span></div>${o.exists&&o.download_url?`<a class="btn mini primary" href="${o.download_url}">下载</a>`:'<span class="pill warn">文件不可用</span>'}</div>`).join('')||'<span class="muted-line">暂无可下载产物</span>'}
  function historyHtml428(aid,vid,r){const rows=r?.items||[],v=r?.version||{};return `<div class="convert428"><div class="convert428-top"><div><b>${esc(v.version_name||'-')}</b><span>${rows.length} 条转换记录</span></div><div class="row"><button class="btn" onclick="refreshVersionConvert428('${aid}','${vid}')">刷新</button>${String(v.stored_path||'').trim()?`<button class="btn primary" onclick="openNewConvert428('${aid}','${vid}')">＋ 新建转换</button>`:''}</div></div>${rows.length?rows.map(j=>`<article class="convert428-job"><header><div><b>${esc(j.target_name||TARGET_NAMES428[j.target]||j.target)}</b><span>${esc(j.resource_name||'-')} · ${dt428(j.created_at)}</span></div>${statusPill428(j.status)}</header><div class="convert428-progress"><i style="width:${Math.max(0,Math.min(100,Number(j.progress||0)))}%"></i></div><p>${esc(j.message||j.stage||'')}</p><div class="convert428-outputs">${deployOutput428(j)}</div></article>`).join(''):`<div class="convert428-empty"><b>这个版本还没有转换记录</b><span>${String(v.stored_path||'').trim()?'选择目标硬件后即可开始转换':'本版本没有可用模型产物，无法进行部署转换'}</span>${String(v.stored_path||'').trim()?`<button class="btn primary" onclick="openNewConvert428('${aid}','${vid}')">选择转换目标</button>`:''}</div>`}</div>`}
  window.openVersionConvert428=async function(aid,vid){try{const r=await deploymentHistory428(aid,vid,false);modal('版本转换',historyHtml428(aid,vid,r),true)}catch(e){toast(e.message||e)}};
  window.refreshVersionConvert428=async function(aid,vid){try{const r=await deploymentHistory428(aid,vid,true);const mb=document.querySelector('.modal-body');if(mb)mb.innerHTML=historyHtml428(aid,vid,r);toast('已重新读取转换记录')}catch(e){toast(e.message||e)}};
  function targetResources428(rows,target){return(rows||[]).filter(x=>x.status==='ready'&&(x.targets||[]).includes(target))}
  window.openNewConvert428=async function(aid,vid){try{const rr=await deployResources428(false),hist=await deploymentHistory428(aid,vid,false),v=hist.version||{};if(!String(v.stored_path||'').trim())return toast('当前版本没有可用模型产物');modal('新建版本转换',`<div class="convert428-create"><section><b>源版本</b><div class="convert428-source"><span>${esc(hist.algorithm?.name||'-')}</span><strong>${esc(v.version_name||'-')}</strong><em>${esc(v.model_name||'')}</em></div></section><section><b>转换目标</b><div class="convert428-targets">${['ascend','rockchip','sophon'].map((t,i)=>`<label><input type="radio" name="conv428Target" value="${t}" ${i===0?'checked':''} onchange="refreshConvertResource428()"><i></i><b>${esc(TARGET_NAMES428[t])}</b><span>${t==='ascend'?'输出 .om':t==='rockchip'?'输出 .rknn':'输出 .bmodel'}</span></label>`).join('')}</div></section><section><div class="form two"><div class="field"><label>转换资源</label><select id="conv428Resource" class="select"></select></div><div class="field"><label>精度</label><select id="conv428Precision" class="select"><option value="fp16">FP16</option><option value="fp32">FP32</option><option value="int8">INT8（需要校准数据）</option></select></div><div class="field"><label>输入尺寸</label><input id="conv428Input" class="input" value="640"></div><div class="field"><label>芯片型号</label><input id="conv428Chip" class="input" value=""></div></div></section><div id="conv428Warn" class="alert soft"></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="submitConvert428('${aid}','${vid}')">开始转换</button></div></div>`,true);state.conv428Resources=rr.items||[];setTimeout(refreshConvertResource428,20)}catch(e){toast(e.message||e)}};
  window.refreshConvertResource428=function(){const t=document.querySelector('input[name="conv428Target"]:checked')?.value||'ascend',rows=targetResources428(state.conv428Resources,t),sel=document.getElementById('conv428Resource'),chip=document.getElementById('conv428Chip'),warn=document.getElementById('conv428Warn');if(sel){sel.innerHTML=rows.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')||'<option value="">暂无可用转换资源</option>';sel.onchange=()=>{const r=(state.conv428Resources||[]).find(x=>x.id===sel.value);if(t==='ascend'&&chip){const socs=r?.detected_soc_versions||r?.remote_health?.soc_versions||[];chip.value=socs[0]||''}}}const first=rows[0];if(chip){if(t==='rockchip')chip.value='rk3588';else if(t==='sophon')chip.value='bm1684x';else{const socs=first?.detected_soc_versions||first?.remote_health?.soc_versions||[];chip.value=socs[0]||''}}if(warn)warn.textContent=rows.length?(t==='ascend'&&!chip?.value?'转换资源可用，但未自动识别 Atlas soc_version；请填写最终部署芯片型号，例如 Ascend310P3。':'将使用已检测可用的真实转换资源执行。'):'当前没有已检测为可用的转换资源，请展开“高级功能 → 部署资源”配置并检测后再试。'};
  window.submitConvert428=async function(aid,vid){const target=document.querySelector('input[name="conv428Target"]:checked')?.value||'ascend',rid=document.getElementById('conv428Resource')?.value;if(!rid)return toast('当前目标没有可用转换资源');const precision=document.getElementById('conv428Precision')?.value||'fp16',size=Number(document.getElementById('conv428Input')?.value||640),chip=document.getElementById('conv428Chip')?.value.trim()||'';const params={precision,input_size:size};if(chip){params.chip=chip;if(target==='ascend')params.soc_version=chip}if(target==='ascend'&&!chip)return toast('华为 Atlas 转换必须填写 soc_version，例如 Ascend310P3');try{await api(`/api/v39/projects/${pid()}/deploy/jobs`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_id:`version::${aid}::${vid}`,target,resource_id:rid,params,dataset_id:'default',calibration_split:'train',calibration_count:100})});localStorage.removeItem(cacheKey428('verdeploy',aid,vid));closeModal();const r=await deploymentHistory428(aid,vid,true);modal('版本转换',historyHtml428(aid,vid,r),true);toast('转换任务已创建')}catch(e){toast(e.message||e)}};

  // ---------------------- training creation from algorithm ----------------------
  function baseCfg428(){return{model:'',epochs:100,imgsz:640,batch:8,device:'cpu',optimizer:'auto',patience:100,workers:0,lr0:.01,lrf:.01,momentum:.937,weight_decay:.0005,warmup_epochs:3,close_mosaic:10,mosaic:1,mixup:0,hsv_h:.015,hsv_s:.7,hsv_v:.4,degrees:0,translate:.1,scale:.5,shear:0,perspective:0,flipud:0,fliplr:.5,cache:'False',pretrained:true,amp:true,rect:false,cos_lr:false,freeze:0,multi_scale:0,save_period:-1,seed:0,deterministic:true,eval_interval:10,eval_metric:'map50',continue_threshold:0,stop_threshold:.90,val_max_samples:0,queue_priority:50,auto_convert_targets:[]}}
  function trainingConfig428(){const draft=state.trainingDraft||{},resource=draft.resource||{},c=Object.assign(baseCfg428(),draft.config||{});if(resource.device&&resource.device!=='auto')c.device=resource.device;if(resource.batch!=null)c.batch=resource.batch;if(resource.workers!=null)c.workers=resource.workers;if(resource.cache!=null)c.cache=resource.cache===false?'False':resource.cache;if(resource.strategy)c.resource_strategy=resource.strategy;if(resource.gpuPolicy)c.gpu_policy=resource.gpuPolicy;return c}
  window.trainingConfigCanonical428=trainingConfig428;
  function selectedTarget428(){const id=document.getElementById('tr429Target')?.value||document.getElementById('tr428Target')?.value||'';return(state.targets||[]).find(x=>String(x.id)===String(id))}

  window.openTrainSettings428=function(){const c=trainingConfig428(),t=selectedTarget428(),models=t?.base_models||[];modal('训练配置设置',`<div class="train428-settings">
    <section><header><b>基础训练</b><span>普通用户通常只需要调整总轮数，其余可使用默认值</span></header><div class="form four"><div class="field"><label>基础模型</label><select id="ts428Model" class="select">${models.map(m=>`<option value="${esc(m.value||m.label)}" ${(m.value||m.label)===c.model?'selected':''}>${esc(m.label||m.value)}</option>`).join('')||`<option value="${esc(c.model)}">${esc(c.model||'-')}</option>`}</select></div><div class="field"><label>总轮数 Epoch</label><input id="ts428Epoch" class="input" type="number" min="1" value="${c.epochs}"></div><div class="field"><label>图片尺寸</label><input id="ts428Size" class="input" type="number" min="32" value="${c.imgsz}"></div><div class="field"><label>Batch</label><input id="ts428Batch" class="input" type="number" value="${c.batch}"></div></div></section>
    <section class="train428-gate"><header><b>阶段试验与门禁</b><span>不使用 AI；以试验集人工标注计算的客观指标做判断</span></header><div class="train428-gate-flow"><div><b>训练</b><span>正常进行</span></div><i>→</i><div><b>每 N 轮检查</b><span>随机抽试验集</span></div><i>→</i><div><b>门禁判断</b><span>继续 / 停止 / 达标</span></div></div><div class="form four"><div class="field"><label>每隔几轮检查</label><input id="ts428EvalInt" class="input" type="number" min="1" value="${c.eval_interval||10}"></div><div class="field"><label>每次随机抽取试验集</label><input id="ts428ValN" class="input" type="number" min="0" value="${c.val_max_samples||0}"><small>0 = 使用全部试验集</small></div><div class="field"><label>门禁指标</label><select id="ts428Metric" class="select"><option value="map50" ${c.eval_metric==='map50'?'selected':''}>mAP50（推荐）</option><option value="recall" ${c.eval_metric==='recall'?'selected':''}>Recall</option><option value="precision" ${c.eval_metric==='precision'?'selected':''}>Precision</option></select></div><div class="field"><label>低于此正确率停止</label><div class="input-suffix428"><input id="ts428Low" class="input" type="number" min="0" max="100" step="0.1" value="${Math.round((c.continue_threshold||0)*1000)/10}"><span>%</span></div><small>0 = 不启用低分停止</small></div><div class="field"><label>达到此正确率即达标</label><div class="input-suffix428"><input id="ts428Goal" class="input" type="number" min="0" max="100" step="0.1" value="${Math.round((c.stop_threshold||.9)*1000)/10}"><span>%</span></div></div></div></section>
    <section><header><b>达标后自动转换</b><span>只有达到上面的目标正确率才触发；转换失败不会影响算法版本生成</span></header><div class="train428-convert-checks">${['ascend','rockchip','sophon'].map(x=>`<label><input type="checkbox" class="ts428AutoConvert" value="${x}" ${(c.auto_convert_targets||[]).includes(x)?'checked':''}><i></i><div><b>${esc(TARGET_NAMES428[x])}</b><span>${x==='ascend'?'.om':x==='rockchip'?'.rknn':'.bmodel'}</span></div></label>`).join('')}</div></section>
    <details class="advanced427-box"><summary>高级训练参数</summary><div class="form four"><div class="field"><label>Optimizer</label><select id="ts428Opt" class="select">${['auto','SGD','Adam','AdamW','NAdam','RAdam','RMSProp'].map(x=>`<option ${c.optimizer===x?'selected':''}>${x}</option>`).join('')}</select></div><div class="field"><label>Early Stop patience</label><input id="ts428Patience" class="input" type="number" value="${c.patience}"></div><div class="field"><label>Workers</label><input id="ts428Workers" class="input" type="number" value="${c.workers}"></div><div class="field"><label>初始学习率 lr0</label><input id="ts428Lr0" class="input" type="number" step="0.0001" value="${c.lr0}"></div><div class="field"><label>Momentum</label><input id="ts428Momentum" class="input" type="number" step="0.001" value="${c.momentum}"></div><div class="field"><label>Weight Decay</label><input id="ts428WD" class="input" type="number" step="0.0001" value="${c.weight_decay}"></div><div class="field"><label>Mosaic</label><input id="ts428Mosaic" class="input" type="number" step="0.1" value="${c.mosaic}"></div><div class="field"><label>MixUp</label><input id="ts428Mixup" class="input" type="number" step="0.1" value="${c.mixup}"></div><div class="field"><label>随机种子</label><input id="ts428Seed" class="input" type="number" value="${c.seed}"></div><div class="field"><label>Checkpoint间隔</label><input id="ts428Save" class="input" type="number" value="${c.save_period}"></div><div class="field"><label>冻结前N层</label><input id="ts428Freeze" class="input" type="number" value="${c.freeze}"></div><div class="field"><label>缓存</label><select id="ts428Cache" class="select"><option value="False" ${c.cache==='False'?'selected':''}>关闭</option><option value="ram" ${c.cache==='ram'?'selected':''}>内存</option><option value="disk" ${c.cache==='disk'?'selected':''}>磁盘</option></select></div></div><div class="train428-mini-checks"><label><input id="ts428Pretrained" type="checkbox" ${c.pretrained?'checked':''}>预训练权重</label><label><input id="ts428Amp" type="checkbox" ${c.amp?'checked':''}>AMP混合精度</label><label><input id="ts428Det" type="checkbox" ${c.deterministic?'checked':''}>确定性训练</label><label><input id="ts428Cos" type="checkbox" ${c.cos_lr?'checked':''}>余弦学习率</label></div></details>
    <div class="row end sticky-actions425"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveTrainSettings428()">应用配置</button></div></div>`,true)};
  window.saveTrainSettings428=function(){const c=trainingConfig428(),num=(id,d)=>{const e=document.getElementById(id);return e?Number(e.value||d):d},low=num('ts428Low',0)/100,goal=num('ts428Goal',90)/100;if(goal>0&&low>0&&low>=goal)return toast('“低于停止”必须小于“达到达标”的正确率');Object.assign(c,{model:document.getElementById('ts428Model')?.value||c.model,epochs:num('ts428Epoch',100),imgsz:num('ts428Size',640),batch:num('ts428Batch',8),eval_interval:Math.max(1,num('ts428EvalInt',10)),val_max_samples:Math.max(0,num('ts428ValN',0)),eval_metric:document.getElementById('ts428Metric')?.value||'map50',continue_threshold:low,stop_threshold:goal,optimizer:document.getElementById('ts428Opt')?.value||'auto',patience:num('ts428Patience',100),workers:num('ts428Workers',0),lr0:num('ts428Lr0',.01),momentum:num('ts428Momentum',.937),weight_decay:num('ts428WD',.0005),mosaic:num('ts428Mosaic',1),mixup:num('ts428Mixup',0),seed:num('ts428Seed',0),save_period:num('ts428Save',-1),freeze:num('ts428Freeze',0),cache:document.getElementById('ts428Cache')?.value||'False',pretrained:!!document.getElementById('ts428Pretrained')?.checked,amp:!!document.getElementById('ts428Amp')?.checked,deterministic:!!document.getElementById('ts428Det')?.checked,cos_lr:!!document.getElementById('ts428Cos')?.checked,auto_convert_targets:[...document.querySelectorAll('.ts428AutoConvert:checked')].map(x=>x.value)});window.TrainingDraftRuntime?.update?.({config:c,resource:{batch:c.batch,workers:c.workers,cache:c.cache==='False'?false:c.cache}});closeModal();window.refreshTrain429?.();toast('训练配置已应用')};
  
  // ---------------------- training task center: active/history only ----------------------
  function priorityValue428(j){const raw=Number(j?.queue_priority??50);if(j?.priority_scheme==='lower_number_first')return Math.max(1,Math.min(999,Number.isFinite(raw)?raw:50));const legacy={100:1,80:20,50:50};return legacy[raw]??Math.max(1,Math.min(999,101-(Number.isFinite(raw)?raw:50)))}
  function queueOrder428(a,b){return priorityValue428(a)-priorityValue428(b)||(Number(a.priority_tiebreaker||0)-Number(b.priority_tiebreaker||0))||String(a.queued_at||a.created_at||'').localeCompare(String(b.queued_at||b.created_at||''))||String(a.id||'').localeCompare(String(b.id||''))}
  function queuePosition428(j){if(j.status!=='queued')return'';const same=(state.jobs||[]).filter(x=>x.status==='queued'&&(x.resource_key||'')===(j.resource_key||'')).sort(queueOrder428);const i=same.findIndex(x=>x.id===j.id);return i>=0?`队列第 ${i+1} 位`:''}
  function trainActions428(j){if(j.status==='queued')return`<button class="btn mini" onclick="promoteTrain428('${j.id}')">插队</button><button class="btn mini danger" onclick="stopTrain428('${j.id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${j.id}')">删除</button>`;if(j.status==='running')return`<button class="btn mini" onclick="showTrainLog423('${j.id}')">日志</button><button class="btn mini" onclick="pauseTrain428('${j.id}')">暂停</button><button class="btn mini danger" onclick="stopTrain428('${j.id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${j.id}')">删除</button>`;if(j.status==='paused')return`<button class="btn mini" onclick="showTrainLog423('${j.id}')">日志</button><button class="btn mini primary" onclick="resumeTrain428('${j.id}')">继续</button><button class="btn mini danger" onclick="stopTrain428('${j.id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${j.id}')">删除</button>`;return`<button class="btn mini" onclick="showTrainLog423('${j.id}')">日志</button>${j.auto_version_id?`<button class="btn mini primary" onclick="trainingReport425('${j.id}')">训练报告</button>`:''}<button class="btn mini danger" onclick="deleteTrain428('${j.id}')">删除</button>`}
  function trainRows428(rows){const ordered=[...rows].sort((a,b)=>{const ar=a.status==='running'?0:a.status==='paused'?1:a.status==='queued'?2:3,br=b.status==='running'?0:b.status==='paused'?1:b.status==='queued'?2:3;return ar-br||(ar===2?queueOrder428(a,b):String(b.started_at||b.created_at||'').localeCompare(String(a.started_at||a.created_at||'')))});return ordered.map(j=>`<tr><td><div class="train428-taskname"><b>${esc(j.asset_algorithm_name||j.algorithm_name||j.id)}</b><span>${esc(j.id)}</span>${j.auto_version_name?`<em>版本 ${esc(j.auto_version_name)}</em>`:''}</div></td><td>${statusPill428(j.status)}<small class="queuepriority428">优先级 ${priorityValue428(j)}</small>${queuePosition428(j)?`<small class="queuepos428">${queuePosition428(j)}</small>`:''}</td><td><div class="train428-resource"><b>${esc(resourceName428(j))}</b><span>${esc(j.framework==='paddle'?'PaddleDetection':'Ultralytics / YOLO')}</span></div></td><td><div class="progress424"><i style="width:${Math.max(0,Math.min(100,Number(j.progress_percent||0)))}%"></i></div><span class="train428-progress-txt">${j.current_epoch||0}/${j.total_epochs||j.epochs||'-'} · ${Number(j.progress_percent||0).toFixed(0)}%</span></td><td>${fmtTime424(j.elapsed_seconds)}</td><td>${fmtTime424(j.eta_seconds)}</td><td>${dt428(j.started_at||j.created_at)}</td><td><div class="row wrap">${trainActions428(j)}</div></td></tr>`).join('')||'<tr><td colspan="8" class="empty-row">暂无记录</td></tr>'}
  window.renderTraining425=window.renderTraining424=window.renderTraining423=function(){const active=(state.jobs||[]).filter(j=>ACTIVE428.has(j.status)),history=(state.jobs||[]).filter(j=>DONE428.has(j.status));const rows=state.train428Tab==='active'?active:history;document.getElementById('view').innerHTML=`<section class="train428-page"><div class="train428-tabs"><button class="${state.train428Tab==='active'?'on':''}" onclick="setTrainTab428('active')">进行中 <span>${active.length}</span></button><button class="${state.train428Tab==='history'?'on':''}" onclick="setTrainTab428('history')">历史记录 <span>${history.length}</span></button><button class="train428-refresh" onclick="refreshTrainPage428()">刷新</button></div><section class="panel"><div class="table-wrap"><table class="table train428-table"><thead><tr><th>训练任务</th><th>状态</th><th>执行机器 / 框架</th><th>进度</th><th>已用时间</th><th>预计剩余</th><th>开始时间</th><th>操作</th></tr></thead><tbody>${trainRows428(rows)}</tbody></table></div></section></section>`;window.PollRegistryRuntime?.replaceTrainingJobTimer?.()};
  window.setTrainTab428=function(t){state.train428Tab=t;renderTraining423()};
  window.refreshTrainPage428=async function(){await loadRelated();renderTraining423();toast('训练任务已刷新')};
  window.promoteTrain428=async function(id){try{await api(`/api/v48/projects/${pid()}/jobs/${id}/promote`,{method:'POST'});await loadRelated();renderTraining423();toast('任务已插到当前资源队列最前')}catch(e){toast(e.message||e)}};
  window.pauseTrain428=async function(id){try{await api(`/api/v48/projects/${pid()}/jobs/${id}/pause`,{method:'POST'});await loadRelated();renderTraining423();toast('训练已暂停')}catch(e){toast(e.message||e)}};
  window.resumeTrain428=async function(id){try{await api(`/api/v48/projects/${pid()}/jobs/${id}/resume`,{method:'POST'});await loadRelated();renderTraining423();toast('训练已继续')}catch(e){toast(e.message||e)}};
  window.stopTrain428=async function(id){if(!confirm('确认停止这个训练任务？已经开始过的任务会按当前训练结束时间自动形成一个算法版本。'))return;try{await api(`/api/v48/projects/${pid()}/jobs/${id}/stop`,{method:'POST'});await loadRelated();renderTraining423();toast('训练已停止')}catch(e){toast(e.message||e)}};
  window.deleteTrain428=async function(id){if(!confirm('确认删除这条训练任务记录？已经生成的算法版本不会删除。'))return;const j=(state.jobs||[]).find(x=>x.id===id);try{if(j&&['running','paused','queued'].includes(j.status))await api(`/api/v48/projects/${pid()}/jobs/${id}/stop`,{method:'POST'});await api(`/api/v12/projects/${pid()}/jobs/${id}`,{method:'DELETE'});await loadRelated();renderTraining423();toast('任务记录已删除')}catch(e){toast(e.message||e)}};

  // ---------------------- executive training timeline without AI ----------------------
  window.showTrainLog423=async function(id){const j=(state.jobs||[]).find(x=>x.id===id)||{},txt=await safe(api(`/api/projects/${pid()}/jobs/${id}/log`))||'',p=Number(j.progress_percent||0),ep=j.current_epoch||0,total=j.total_epochs||j.epochs||0,gate=j.gate_events||[];let headline='训练任务正在等待资源';if(j.status==='running')headline=p<25?'模型正在学习基础特征':p<75?'模型进入主要学习阶段':'模型正在收敛，接近训练后段';if(j.status==='paused')headline='训练已暂停，当前进度和模型检查点已保留';if(['done','finished','completed'].includes(j.status))headline='训练已完成，并已自动归档算法版本';if(j.status==='stopped')headline='训练已人工停止，并按当前成果归档版本';if(j.status==='failed')headline='训练异常结束，系统仍保留本次迭代记录';const events=[{title:'进入训练队列',text:`执行资源：${resourceName428(j)}`,done:true},...(j.started_at?[{title:'开始训练',text:`训练 ${j.dataset_counts?.train||0} 张 · 试验 ${j.dataset_counts?.val||0} 张`,done:true}]:[]),...gate.map(g=>({title:`阶段检查 · 第 ${g.epoch} 轮`,text:`随机抽取 ${g.sample_count||j.quality_gate?.stage_eval_samples||'全部'} 张试验集 · ${gateMetricName428(g.metric||j.quality_gate?.metric)} ${metricPct428(g.value)} · ${gateDecision428(g)}`,done:true})),...(j.auto_version_name?[{title:'自动生成版本',text:`版本 ${j.auto_version_name}${j.training_report?.metrics?.['metrics/mAP50(B)']!=null?` · 正确率 ${metricPct428(j.training_report.metrics['metrics/mAP50(B)'])}`:''}`,done:true}]:[]),...((j.auto_conversion?.jobs||[]).length?[{title:'达标后自动转换',text:`已创建 ${(j.auto_conversion.jobs||[]).length} 个转换任务`,done:true}]:[])];if(!DONE428.has(j.status))events.push({title:j.status==='paused'?'当前暂停位置':j.status==='queued'?'等待执行':'当前训练',text:`Epoch ${ep}/${total||'-'} · ${p.toFixed(0)}%`,current:true});modal('训练运行中心',`<div class="trainlog428"><section class="trainlog427-hero"><div><span>当前判断</span><h2>${esc(headline)}</h2><p>${esc(j.message||'系统按训练轮次执行阶段检查，并记录每次门禁结果。')}</p></div><div class="trainlog427-kpis"><div><span>整体进度</span><b>${p.toFixed(0)}%</b></div><div><span>轮次</span><b>${ep}/${total||'-'}</b></div><div><span>已用时间</span><b>${fmtTime424(j.elapsed_seconds)}</b></div><div><span>预计剩余</span><b>${fmtTime424(j.eta_seconds)}</b></div></div></section><section class="trainlog428-resource"><div><span>执行机器</span><b>${esc(resourceName428(j))}</b></div><div><span>阶段门禁</span><b>${j.quality_gate?.eval_interval?`每 ${j.quality_gate.eval_interval} 轮检查 · ${j.quality_gate.stage_eval_samples>0?j.quality_gate.stage_eval_samples+' 张':'全部试验集'}`:'未配置'}</b></div><div><span>达标指标</span><b>${gateMetricName428(j.quality_gate?.metric)} ${j.quality_gate?.stop_threshold>0?metricPct428(j.quality_gate.stop_threshold):'-'}</b></div></section><section class="trainlog427-flow">${events.map(x=>`<div class="${x.current?'current':''}"><i></i><section><b>${esc(x.title)}</b><span>${esc(x.text)}</span></section></div>`).join('')}</section><details class="trainlog427-tech"><summary>工程师技术日志</summary><pre class="log train423-log">${esc(txt||'暂无技术日志')}</pre></details><div class="row end"><button class="btn" onclick="refreshTrainLog428('${id}')">刷新</button><button class="btn" onclick="closeModal()">关闭</button></div></div>`,true)};
  window.refreshTrainLog428=async function(id){await loadRelated();closeModal();showTrainLog423(id)};

  // Keep report wording aligned with v42.8 random stage trials.
  const report425Base428=window.trainingReport425;
  window.trainingReport425=window.trainingReport424=async function(id){await report425Base428(id);setTimeout(()=>{document.querySelectorAll('.report425-gate-summary span').forEach(el=>{el.innerHTML=el.innerHTML.replace('固定试验样本','每次随机试验样本')})},20)};

  // Final route override: task center never exposes a create button; algorithm list is the only training entry.
  const renderBase428=render;
  render=function(){if(state.page==='训练任务'){renderNav();renderTop();renderSummary();renderTraining423();return}renderBase428()};
  window.startAlgorithmTraining428=window.startAlgorithmTraining423;
})();

/* ============================================================
   v42.9 — algorithm report + processed data pool + faster review
   ============================================================ */
(()=>{
  const V429='42.24.0';
  state.data429Tab=state.data429Tab||'unprocessed';
  state.data429Labels=state.data429Labels||new Set();
  state.data429Page=state.data429Page||1;
  state.data429PageSize=48;
  state.ai429RefLabels=state.ai429RefLabels||new Set();
  state.ai429RefSelected=state.ai429RefSelected||new Set();

  const dt429=v=>v?String(v).replace('T',' ').replace('Z','').slice(0,19):'-';
  const pct429=v=>{if(v==null||v===''||Number.isNaN(Number(v)))return '-';let n=Number(v);if(n<=1)n*=100;return n.toFixed(1)+'%'};
  const algType429=id=>({yolo_ultralytics:'YOLO / Ultralytics',paddle_detection:'PaddleDetection',opencv:'OpenCV 传统视觉',mmdetection:'MMDetection',custom_python:'自定义 Python / 其他'})[id]||id||'其他算法';
  const processed429=x=>(x.processing_status||'unprocessed')==='processed';
  function metric429(v){const r=v?.report||{},m=r.metrics||{};return m['metrics/mAP50(B)']??m.map50??m.mAP50??v?.accuracy??null}
  function active429(a){return(state.jobs||[]).find(j=>(j.asset_algorithm_id===a.id||j.algorithm_asset_id===a.id)&&['queued','running','paused','waiting','pending'].includes(j.status))}
  function targetName429(t){return t?.name||t?.base_url||'训练资源'}
  function status429(s){return({queued:'排队中',running:'训练中',paused:'已暂停',done:'已完成',finished:'已完成',completed:'已完成',failed:'失败',stopped:'已停止'})[s]||s||'-'}

  // ---------- algorithm list: every asset can start a training iteration ----------
  function verRow429(a,v){const can=!!String(v.stored_path||'').trim();return `<div class="alg428-version-row">
    <div class="alg428-version-id"><i></i><div><b>${esc(v.version_name||'-')}</b><span>${dt429(v.finished_at||v.created_at)}</span></div></div>
    <div class="alg428-version-status"><span>训练状态</span><b>${esc(status429(v.training_status||v.status||'done'))}</b></div>
    <div class="alg428-version-accuracy"><span>正确率 · mAP50</span><b>${pct429(metric429(v))}</b></div>
    <div class="alg428-version-model"><span>训练成果</span><b>${can?esc(v.model_name||'模型文件'):'无模型文件'}</b></div>
    <div class="alg428-version-actions"><button class="btn mini" onclick="event.stopPropagation();openVersionReport429('${a.id}','${v.id}')">训练报告</button><button class="btn mini primary" onclick="event.stopPropagation();openVersionConvert428('${a.id}','${v.id}')">转换</button>${can?`<a class="btn mini" onclick="event.stopPropagation()" href="/api/v12/projects/${pid()}/algorithms/${a.id}/versions/${v.id}/download">下载模型</a>`:''}</div>
  </div>`}
  window.renderAlgorithms423=async function(){
    const inds=[...new Set((state.algorithms||[]).map(a=>a.industry).filter(Boolean))].sort();
    document.getElementById('view').innerHTML=`<section class="alg428-shell"><div class="alg428-toolbar"><div class="filter423"><input id="alg429Q" class="input" placeholder="搜索算法" oninput="renderAlg429()"><select id="alg429Industry" class="select" onchange="renderAlg429()"><option value="all">全部行业场景</option>${inds.map(x=>`<option>${esc(x)}</option>`).join('')}</select><select id="alg429Type" class="select" onchange="renderAlg429()"><option value="all">全部算法类型</option><option value="yolo_ultralytics">YOLO / Ultralytics</option><option value="paddle_detection">PaddleDetection</option><option value="opencv">OpenCV 传统视觉</option><option value="mmdetection">MMDetection</option><option value="custom_python">自定义 Python / 其他</option></select></div><button class="btn primary" onclick="openNewAlgorithm423()">＋ 新建算法</button></div><div id="alg429List" class="alg428-list"></div></section>`;renderAlg429();
  };
  window.renderAlg429=function(){const q=(document.getElementById('alg429Q')?.value||'').toLowerCase(),ind=document.getElementById('alg429Industry')?.value||'all',typ=document.getElementById('alg429Type')?.value||'all';const rows=(state.algorithms||[]).filter(a=>(!q||`${a.name} ${a.remark||''} ${a.industry||''} ${a.algorithm_type||''}`.toLowerCase().includes(q))&&(ind==='all'||a.industry===ind)&&(typ==='all'||a.algorithm_type===typ));const box=document.getElementById('alg429List');if(!box)return;box.innerHTML=rows.map(a=>{const vs=a.versions||[],latest=vs[0],run=active429(a),open=!!state.alg428Expanded?.[a.id];return `<article class="alg428-card ${open?'open':''}"><div class="alg428-main" onclick="toggleAlgorithm428('${a.id}')"><div class="alg428-logo">${esc((a.name||'算').slice(0,1))}</div><div class="alg428-info"><div class="alg428-title"><b>${esc(a.name)}</b><span>${esc(algType429(a.algorithm_type))}</span>${a.industry?`<em>${esc(a.industry)}</em>`:''}</div><p>${esc(a.remark||'')}</p><div class="alg428-meta"><span>训练次数 <b>${(state.jobs||[]).filter(j=>j.asset_algorithm_id===a.id||j.algorithm_asset_id===a.id).length}</b></span><span>版本 <b>${vs.length}</b></span><span>最新正确率 <b>${pct429(metric429(latest))}</b></span></div></div><div class="alg428-state">${run?`<span class="alg428-running">${esc(status429(run.status))}</span><small>${esc(run.execution_resource?.name||run.server_name||'训练资源')}</small>`:`<span class="alg429-last">${latest?'最新 '+esc(latest.version_name):'尚未训练'}</span>`}</div><div class="alg428-actions" onclick="event.stopPropagation()"><button class="btn mini" onclick="viewAlgorithm429('${a.id}')">详情</button><button class="btn mini" onclick="algorithmReport429('${a.id}')">综合报告</button><button class="btn mini" onclick="editAlgorithm423('${a.id}')">编辑</button><button class="btn mini primary" onclick="startAlgorithmTraining429('${a.id}')">训练</button><button class="btn mini danger" onclick="delAlgorithm('${a.id}')">删除</button><i class="alg428-chevron">⌄</i></div></div>${open?`<div class="alg428-versions"><div class="alg428-version-head"><b>迭代版本</b><span>每次训练结束自动形成时间版本</span></div>${vs.length?vs.map(v=>verRow429(a,v)).join(''):'<div class="empty alg428-empty">暂无版本，点击“训练”开始第一次迭代</div>'}</div>`:''}</article>`}).join('')||'<div class="empty">暂无算法</div>'};
  window.viewAlgorithm429=function(id){const a=(state.algorithms||[]).find(x=>x.id===id);if(!a)return;const vs=a.versions||[];modal('算法详情',`<div class="alg428-detail"><section><div class="alg428-detail-name"><div class="alg428-logo">${esc((a.name||'算').slice(0,1))}</div><div><h2>${esc(a.name)}</h2><span>${esc(algType429(a.algorithm_type))}${a.industry?` · ${esc(a.industry)}`:''}</span></div></div><p>${esc(a.remark||'')}</p><div class="row"><button class="btn primary" onclick="startAlgorithmTraining429('${a.id}')">开始训练</button><button class="btn" onclick="algorithmReport429('${a.id}')">查看综合训练报告</button></div></section><section><div class="alg428-version-head"><b>版本列表</b><span>${vs.length} 个版本</span></div>${vs.length?vs.map(v=>verRow429(a,v)).join(''):'<div class="empty">暂无版本</div>'}</section></div>`,true)};

  function spark429(points,w=720,h=190){const vals=points.map(x=>Number(x)).filter(Number.isFinite);if(!vals.length)return '<div class="empty">暂无可绘制的准确率数据</div>';const min=Math.min(...vals,0),max=Math.max(...vals,1),pad=18;const xy=vals.map((v,i)=>{const x=pad+(w-pad*2)*(vals.length===1?.5:i/(vals.length-1));const y=h-pad-(h-pad*2)*(v-min)/Math.max(.0001,max-min);return[x,y]});return `<svg class="report429-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><line x1="${pad}" y1="${h-pad}" x2="${w-pad}" y2="${h-pad}"/><polyline points="${xy.map(p=>p.join(',')).join(' ')}"/>${xy.map((p,i)=>`<circle cx="${p[0]}" cy="${p[1]}" r="4"><title>${pct429(vals[i])}</title></circle>`).join('')}</svg>`}
  window.algorithmReport429=async function(id){try{const r=await api(`/api/v49/projects/${pid()}/algorithms/${id}/report`),a=r.algorithm||{},s=r.summary||{},trend=(r.trend||[]).filter(x=>x.map50!=null),labs=Object.entries(s.label_counts||{}).sort((a,b)=>b[1]-a[1]);modal('算法综合训练报告',`<div class="report429"><section class="report429-head"><div><span>算法长期训练总结</span><h2>${esc(a.name||'')}</h2><p>${esc(algType429(a.algorithm_type))}${a.industry?` · ${esc(a.industry)}`:''}</p></div><div class="report429-kpis"><div><span>累计训练</span><b>${s.training_count||0} 次</b></div><div><span>版本数量</span><b>${a.version_count||0}</b></div><div><span>最新正确率</span><b>${pct429(s.latest_accuracy)}</b></div><div><span>累计训练时长</span><b>${fmtTime424(s.total_duration_seconds||0)}</b></div></div></section><section class="report429-card"><header><b>历次训练准确率走势</b><span>每个点代表一次训练完成后的 mAP50</span></header>${spark429(trend.map(x=>x.map50))}<div class="report429-legend">${trend.map(x=>`<span>${esc(x.version||x.job_id||'-')} <b>${pct429(x.map50)}</b></span>`).join('')}</div></section><div class="report429-cols"><section class="report429-card"><header><b>训练素材标签维度</b><span>累计参与训练的检测框数量</span></header><div class="report429-bars">${labs.map(([k,v])=>`<div><span>${esc(k)}</span><i><em style="width:${Math.min(100,v/Math.max(1,labs[0]?.[1]||1)*100)}%"></em></i><b>${v}</b></div>`).join('')||'<div class="empty">暂无标签统计</div>'}</div></section><section class="report429-card"><header><b>算法档案</b></header><dl class="report429-dl"><dt>算法类型</dt><dd>${esc(algType429(a.algorithm_type))}</dd><dt>行业场景</dt><dd>${esc(a.industry||'-')}</dd><dt>训练成功</dt><dd>${s.successful_count||0} / ${s.training_count||0} 次</dd><dt>平均训练时长</dt><dd>${fmtTime424(s.avg_duration_seconds||0)}</dd><dt>当前版本</dt><dd>${esc(s.latest_version||'-')}</dd></dl></section></div><section class="report429-card"><header><b>历次训练记录</b></header><div class="table-wrap"><table class="table"><thead><tr><th>版本/任务</th><th>完成时间</th><th>正确率</th><th>训练素材</th><th>状态</th><th>报告</th></tr></thead><tbody>${(r.trend||[]).slice().reverse().map(x=>`<tr><td>${esc(x.version||x.job_id||'-')}</td><td>${dt429(x.finished_at)}</td><td><b>${pct429(x.map50)}</b></td><td>${x.images||0} 张</td><td>${esc(status429(x.status))}</td><td><button class="btn mini" onclick="openJobReport429('${x.job_id}')">查看</button></td></tr>`).join('')||'<tr><td colspan="6">暂无训练记录</td></tr>'}</tbody></table></div></section></div>`,true)}catch(e){toast(e.message||e)}};

  window.openVersionReport429=function(aid,vid){const a=(state.algorithms||[]).find(x=>x.id===aid),v=(a?.versions||[]).find(x=>x.id===vid);if(!v)return toast('版本不存在');if(v.job_id)return openJobReport429(v.job_id);modal('版本训练报告',`<div class="report429"><section class="report429-head"><div><span>历史版本</span><h2>${esc(v.version_name||'-')}</h2></div><div class="report429-kpis"><div><span>正确率</span><b>${pct429(metric429(v))}</b></div><div><span>模型</span><b>${esc(v.model_name||'-')}</b></div></div></section><section class="report429-card"><pre>${esc(JSON.stringify(v.report||{},null,2))}</pre></section></div>`,true)};
  window.openJobReport429=async function(jobId){try{const r=await api(`/api/v44/projects/${pid()}/jobs/${jobId}/report`),j=r.job||{},rep=r.report||{},hist=rep.history||[],pc=rep.per_class||[],errs=rep.error_samples||[],cfg=rep.configuration||{},ds=rep.data_summary||{},m=rep.metrics||{},mv=m['metrics/mAP50(B)']??m.map50,pr=m['metrics/precision(B)']??m.precision,rc=m['metrics/recall(B)']??m.recall;let conclusion='本次训练已完成。';if(j.status==='failed')conclusion='本次训练异常结束，建议先处理失败原因再重新训练。';else if(j.status==='stopped')conclusion='本次训练被人工停止，但已保留当前成果和版本记录。';else if(mv!=null)conclusion=Number(mv)>=.9?'本次训练整体效果较好，可进入部署或进一步业务验证。':Number(mv)>=.75?'本次训练具备一定识别能力，建议重点检查弱标签和误检/漏检样本。':'本次训练效果偏低，建议先优化数据质量、标签覆盖和训练参数。';modal('版本训练报告',`<div class="report429"><section class="report429-head"><div><span>训练结论</span><h2>${esc(conclusion)}</h2><p>${esc(j.auto_version_name||jobId)} · ${esc(j.asset_algorithm_name||j.algorithm_name||'')}</p></div><div class="report429-kpis"><div><span>mAP50</span><b>${pct429(mv)}</b></div><div><span>Precision</span><b>${pct429(pr)}</b></div><div><span>Recall</span><b>${pct429(rc)}</b></div><div><span>训练时长</span><b>${fmtTime424(j.elapsed_seconds||rep.summary?.elapsed_seconds||0)}</b></div></div></section><section class="report429-card"><header><b>训练过程趋势</b><span>准确率不是只看最后一个数字，还要看是否稳定收敛</span></header>${spark429(hist.map(x=>x.map50))}<div class="report429-mini">Epoch ${j.current_epoch||j.epochs||'-'} / ${j.epochs||'-'} · 基础模型 ${esc(cfg.model||j.model||'-')} · 图片尺寸 ${cfg.imgsz||'-'} · Batch ${cfg.batch??'-'}</div></section><div class="report429-cols"><section class="report429-card"><header><b>逐标签表现</b></header><table class="table"><thead><tr><th>标签</th><th>Precision</th><th>Recall</th><th>mAP50</th></tr></thead><tbody>${pc.map(x=>`<tr><td>${esc(x.label||x.name||x.class||'-')}</td><td>${pct429(x.precision)}</td><td>${pct429(x.recall)}</td><td>${pct429(x.map50)}</td></tr>`).join('')||'<tr><td colspan="4">暂无逐标签数据</td></tr>'}</tbody></table></section><section class="report429-card"><header><b>阶段门禁</b></header><div class="report429-timeline">${(rep.gate_events||j.gate_events||[]).map(g=>`<div><i></i><b>第 ${g.epoch} 轮</b><span>${esc(g.metric||'mAP50')} ${pct429(g.value)} · ${esc(g.decision||'继续训练')}</span></div>`).join('')||'<div class="empty">本次没有阶段门禁记录</div>'}</div></section></div><section class="report429-card"><header><b>错误样本诊断</b><span>用于定位误检 FP、漏检 FN 和弱标签</span></header><div class="report429-errors">${errs.slice(0,24).map(x=>`<article>${x.url?`<img src="${x.url}" loading="lazy">`:''}<b>${esc(x.filename||x.image_id||'-')}</b><span>漏检 ${x.fn_count||x.fn||0} · 误检 ${x.fp_count||x.fp||0}</span><em>${esc([...(x.fn_labels||[]),...(x.fp_labels||[])].join('、'))}</em></article>`).join('')||'<div class="empty">暂无错误样本明细</div>'}</div></section><section class="report429-card"><details><summary>训练配置与工程信息</summary><pre>${esc(JSON.stringify({configuration:cfg,data_summary:ds,artifacts:rep.summary?.artifacts||[]},null,2))}</pre></details></section></div>`,true)}catch(e){toast(e.message||e)}};

  // ---------- processed/unprocessed dataset ----------
  function matchData429(){const q=(document.getElementById('data429Q')?.value||'').trim().toLowerCase(),ann=document.getElementById('data429Ann')?.value||'all',labs=[...state.data429Labels];return(state.images||[]).filter(x=>{if((processed429(x)?'processed':'unprocessed')!==state.data429Tab)return false;if(q&&!String(x.filename||'').toLowerCase().includes(q))return false;if(ann==='marked'&&!x.annotated)return false;if(ann==='unmarked'&&x.annotated)return false;if(labs.length&&!labs.some(l=>(x.labels||[]).includes(l)))return false;return true})}
  function selectCard429(id){if(state.data426DeleteMode){state.data424Selected.has(id)?state.data424Selected.delete(id):state.data424Selected.add(id);renderData429Cards();return}previewData429(id)}
  window.toggleDataLabel429=function(l){if(l==='__clear__')state.data429Labels.clear();else state.data429Labels.has(l)?state.data429Labels.delete(l):state.data429Labels.add(l);state.data429Page=1;renderDatasets424()};
  window.setData429Tab=function(t){state.data429Tab=t;state.data424Selected.clear();state.data426DeleteMode=false;state.data429Page=1;renderDatasets424()};
  function dataCard429(x){const sel=state.data424Selected.has(x.id);return `<article class="data426-card data429-card ${sel?'selected':''}" onclick="selectCard429('${x.id}')"><div class="data426-pic"><img src="${x.url}" loading="lazy" decoding="async"><span class="data429-process ${processed429(x)?'ok':''}">${processed429(x)?'已处理':'未处理'}</span>${state.data426DeleteMode?`<label class="data426-check" onclick="event.stopPropagation()"><input type="checkbox" ${sel?'checked':''} onchange="selectData429('${x.id}',this.checked)"><i></i></label>`:''}</div><div class="data426-body"><div class="data426-title" title="${esc(x.filename)}">${esc(x.filename)}</div><div class="data426-meta"><span>${fmtSize424(x.size_bytes)}</span><span>${x.annotated?'已标注':'未标注'}</span><span>${esc(String(x.created_at||'').slice(0,10))}</span></div><div class="data426-tags">${(x.labels||[]).map(l=>`<span>${esc(l)}</span>`).join('')||'<em>无标签</em>'}</div><div class="data426-actions" onclick="event.stopPropagation()"><button class="btn mini" onclick="editData427('${x.id}')">编辑</button><button class="btn mini" onclick="previewData429('${x.id}')">详情</button><button class="btn mini primary" onclick="openAnnotation('${x.id}')">标注</button></div></div></article>`}
  window.selectCard429=selectCard429;window.selectData429=(id,on)=>{on?state.data424Selected.add(id):state.data424Selected.delete(id);renderData429Cards()};
  window.renderData429Cards=function(){const all=matchData429(),pages=Math.max(1,Math.ceil(all.length/state.data429PageSize));state.data429Page=Math.min(state.data429Page,pages);const st=(state.data429Page-1)*state.data429PageSize,rows=all.slice(st,st+state.data429PageSize);const g=document.getElementById('data429Grid');if(g)g.innerHTML=rows.map(dataCard429).join('')||'<div class="empty data426-empty">当前筛选条件下没有图片</div>';const c=document.getElementById('data429Count');if(c)c.textContent=`${all.length} 张`;const sc=document.getElementById('data429Selected');if(sc)sc.textContent=`已选 ${state.data424Selected.size} 张`;const p=document.getElementById('data429Pager');if(p)p.innerHTML=`<button class="btn mini" ${state.data429Page<=1?'disabled':''} onclick="dataPage429(-1)">上一页</button><span>${state.data429Page} / ${pages}</span><button class="btn mini" ${state.data429Page>=pages?'disabled':''} onclick="dataPage429(1)">下一页</button>`};
  window.dataPage429=d=>{state.data429Page=Math.max(1,state.data429Page+d);renderData429Cards()};
  window.renderDatasets424=function(){const un=(state.images||[]).filter(x=>!processed429(x)).length,pr=(state.images||[]).filter(processed429).length,chips=(state.labels||[]).map(l=>`<button class="data426-chip ${state.data429Labels.has(l.code)?'on':''}" onclick="toggleDataLabel429('${esc(l.code)}')">${esc(l.display_name||l.code)}</button>`).join('');document.getElementById('view').innerHTML=`<section class="data426-shell"><div class="data426-head"><div class="data424-tabs"><button class="${state.data429Tab==='unprocessed'?'on':''}" onclick="setData429Tab('unprocessed')"><span>未处理</span><b>${un}</b></button><button class="${state.data429Tab==='processed'?'on':''}" onclick="setData429Tab('processed')"><span>已处理</span><b>${pr}</b></button></div><div class="row"><button class="btn primary" onclick="openDataUpload426()">上传</button><button class="btn" onclick="createClean427({image_ids:matchData429().map(x=>x.id)})">一键清洗</button><button class="btn" onclick="createAiLabel429({image_ids:matchData429().filter(x=>!x.annotated).map(x=>x.id)})">AI标注</button><button class="btn danger" onclick="toggleDelete429()">${state.data426DeleteMode?'取消删除':'删除'}</button></div></div><section class="panel data426-panel"><div class="data426-filtertop"><div class="data426-filter-title"><b>标签筛选</b><span>可多选；命中任意一个所选标签都会显示</span></div><div class="data426-chips"><button class="data426-chip clear ${state.data429Labels.size?'':'on'}" onclick="toggleDataLabel429('__clear__')">全部</button>${chips}</div></div><div class="data426-toolbar"><input id="data429Q" class="input" placeholder="搜索图片名称" oninput="state.data429Page=1;renderData429Cards()"><select id="data429Ann" class="select compact427" onchange="state.data429Page=1;renderData429Cards()"><option value="all">全部标注</option><option value="marked">已标注</option><option value="unmarked">未标注</option></select><span id="data429Count"></span>${state.data426DeleteMode?`<b id="data429Selected">已选 ${state.data424Selected.size} 张</b><button class="btn danger" onclick="batchDelete429()">删除已选</button>`:''}</div><div id="data429Grid" class="data426-grid"></div><div id="data429Pager" class="data426-pager"></div></section></section>`;renderData429Cards()};
  window.toggleDelete429=function(){state.data426DeleteMode=!state.data426DeleteMode;state.data424Selected.clear();renderDatasets424()};
  window.batchDelete429=async function(){const ids=[...state.data424Selected];if(!ids.length)return toast('请选择要删除的图片');if(!confirm(`确认删除 ${ids.length} 张图片？`))return;try{await api(`/api/v46/projects/${pid()}/images/batch-delete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:ids})});state.images=(state.images||[]).filter(x=>!state.data424Selected.has(x.id));state.data424Selected.clear();state.data426DeleteMode=false;renderDatasets424();toast('删除完成')}catch(e){toast(e.message||e)}};
  window.previewData429=function(id){const list=matchData429(),i=list.findIndex(x=>x.id===id),x=list[i];if(!x)return;modal('图片详情',`<div class="data429-preview"><div><img src="${x.url}"></div><aside><h2>${esc(x.filename)}</h2><dl><dt>处理状态</dt><dd>${processed429(x)?'已处理':'未处理'}</dd><dt>标注状态</dt><dd>${x.annotated?'已标注':'未标注'}</dd><dt>标签</dt><dd>${esc((x.labels||[]).join('、')||'-')}</dd><dt>尺寸</dt><dd>${x.width||'-'} × ${x.height||'-'}</dd><dt>大小</dt><dd>${fmtSize424(x.size_bytes)}</dd><dt>时间</dt><dd>${dt429(x.created_at)}</dd></dl><div class="row"><button class="btn" onclick="editData427('${x.id}')">编辑名称</button><button class="btn primary" onclick="openAnnotation('${x.id}')">标注</button></div></aside></div>`,true)};

  // ---------- faster cleaning confirmation + full details ----------
  const showTaskBase429=window.showTaskProgress427;
  window.showTaskProgress427=async function(type,id){if(type==='clean'){const t=await safe(fetchTask429(type,id));if(t&&['awaiting_confirmation','done'].includes(t.status))return cleanDetail429(id)}return showTaskBase429(type,id)};
  async function fetchTask429(type,id){if(type==='clean'){const r=await api(`/api/v47/projects/${pid()}/clean-tasks`);return(r.items||[]).find(x=>x.id===id)}const r=await api(`/api/v33/projects/${pid()}/prelabel-tasks`);return(r.items||[]).find(x=>x.id===id)}
  function ruleNames429(r){const a=[];if(r.exact_duplicate)a.push('精确重复');if(r.near_duplicate)a.push(`近似重复（距离≤${r.near_duplicate_hamming??5}）`);if((r.min_width||0)>0||(r.min_height||0)>0)a.push(`最低分辨率 ${r.min_width||0}×${r.min_height||0}`);if((r.max_width||999999)<999999||(r.max_height||999999)<999999)a.push(`最高分辨率 ${r.max_width||'-'}×${r.max_height||'-'}`);if(r.blur_check)a.push(`模糊度阈值 ${r.blur_min_laplacian??45}`);if(r.brightness_check)a.push(`亮度 ${r.brightness_min??15}~${r.brightness_max??245}`);if(r.corrupt_check)a.push('损坏图片');return a}
  window.cleanDetail429=async function(id){try{const r=await api(`/api/v47/projects/${pid()}/clean-tasks/${id}/result`),t=r.task||{},res=r.result||{},items=res.items||[],rules=res.rules||t.request_payload||{},stats={};items.forEach(x=>(x.issues||[]).forEach(y=>{stats[y.name]=(stats[y.name]||0)+1}));state.v427CleanConfirm=new Set(items.filter(x=>x.suggest_delete).map(x=>String(x.image_id)));const total=t.total_images||0;modal('清洗任务详情',`<div class="clean429"><section class="clean429-head"><div><span>任务结果</span><h2>${esc(t.name||'自动清洗')}</h2><p>共检查 ${total} 张，发现 ${items.length} 张需要关注，占 ${total?((items.length/total)*100).toFixed(1):0}%</p></div><div class="clean429-kpi"><b>${items.length}</b><span>问题图片</span></div></section><section class="clean429-card"><header><b>本次清洗规则</b></header><div class="clean429-rules">${ruleNames429(rules).map(x=>`<span>${esc(x)}</span>`).join('')||'<span>未记录规则</span>'}</div></section><section class="clean429-card"><header><b>问题分布</b></header><div class="clean429-stats">${Object.entries(stats).map(([k,v])=>`<div><span>${esc(k)}</span><b>${v} 张</b><em>${total?((v/total)*100).toFixed(1):0}%</em></div>`).join('')||'<div class="empty">没有发现不合规图片</div>'}</div></section><section class="clean429-card"><header><b>逐图确认</b><span>默认勾选系统建议剔除的图片；你认为有训练价值的图片可取消勾选保留</span></header><div class="review427-grid">${items.map(x=>`<label class="review427-card"><input type="checkbox" ${state.v427CleanConfirm.has(String(x.image_id))?'checked':''} onchange="toggleCleanItem427('${x.image_id}',this.checked)"><img src="${x.url||((state.images||[]).find(i=>i.id===x.image_id)?.url)||''}" loading="lazy"><b>${esc(x.filename||'')}</b><div>${(x.issues||[]).map(y=>`<span>${esc(y.name)} · ${esc(y.detail)}</span>`).join('')}</div></label>`).join('')||'<div class="empty">本次全部合规，可直接确认进入已处理</div>'}</div></section><div class="row end"><button class="btn" onclick="closeModal()">关闭</button>${t.status==='awaiting_confirmation'?`<button class="btn primary" onclick="confirmClean429('${id}')">确认清洗结果</button>`:''}</div></div>`,true)}catch(e){toast(e.message||e)}};
  window.confirmClean429=async function(id){try{const r=await api(`/api/v47/projects/${pid()}/clean-tasks/${id}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delete_ids:[...state.v427CleanConfirm]})});const del=new Set(r.deleted_ids||[]),proc=new Set(r.processed_ids||[]);state.images=(state.images||[]).filter(x=>!del.has(String(x.id)));state.images.forEach(x=>{if(proc.has(String(x.id))){x.processing_status='processed';x.cleaned_at=new Date().toISOString()}});closeModal();if(state.page==='数据集')renderDatasets424();toast(`清洗确认完成：删除 ${r.deleted||0} 张，其余进入已处理`)}catch(e){toast(e.message||e)}};
  window.confirmClean427=window.confirmClean429;

  // ---------- AI follow-existing filters ----------
  function refs429(){const q=(document.getElementById('ai429RefQ')?.value||'').toLowerCase(),labs=[...state.ai429RefLabels];return(state.images||[]).filter(x=>x.annotated&&(!q||String(x.filename||'').toLowerCase().includes(q))&&(!labs.length||labs.some(l=>(x.labels||[]).includes(l))))}
  window.renderAiRefs429=function(){const g=document.getElementById('ai429RefGrid');if(!g)return;g.innerHTML=refs429().slice(0,40).map(x=>`<button data-image-id="${esc(x.id)}" class="${state.ai429RefSelected.has(x.id)?'on':''}" onclick="toggleRef429('${x.id}')"><img src="${x.url}" loading="lazy"><b>${esc(x.filename)}</b><span>${esc((x.labels||[]).join('、'))}</span></button>`).join('')||'<div class="empty">没有符合筛选条件的已标注图片</div>'};
  window.toggleAiRefLabel429=function(l){state.ai429RefLabels.has(l)?state.ai429RefLabels.delete(l):state.ai429RefLabels.add(l);document.querySelectorAll('.ai429-chip').forEach(b=>b.classList.toggle('on',state.ai429RefLabels.has(b.dataset.label)));renderAiRefs429()};
  window.toggleRef429=function(id){state.ai429RefSelected.has(id)?state.ai429RefSelected.delete(id):state.ai429RefSelected.add(id);renderAiRefs429()};
  window.createAiLabel429=function(opts={}){const ids=opts.image_ids?.length?opts.image_ids:(state.images||[]).filter(x=>!x.annotated).map(x=>x.id),model=(state.modelConfigs||[]).find(x=>x.default_for_annotation)||(state.modelConfigs||[])[0];state.ai429RefLabels=new Set();state.ai429RefSelected=new Set();const chips=(state.labels||[]).map(l=>`<button type="button" class="ai429-chip" data-label="${esc(l.code)}" onclick="toggleAiRefLabel429('${esc(l.code)}')">${esc(l.display_name||l.code)}</button>`).join('');modal('创建AI自动标注任务',`<div class="ailabel427 ai429"><div class="ailabel427-model"><span>系统自动使用</span><b>${esc(model?.name||'未配置AI模型')}</b><em>模型与提示词在高级功能的模型配置中统一维护</em></div><div class="field"><label>直接输入标签</label><input id="ai429Labels" class="input" placeholder="例如：人员、黄色安全帽、烟火"></div><div class="or427"><i></i><span>或者跟随已有标注</span><i></i></div><section class="ai429-ref"><header><div><b>筛选参考素材</b><span>先筛选，再选择已标注图片；系统会提取这些图片的标签</span></div><input id="ai429RefQ" class="input" placeholder="搜索素材名" oninput="renderAiRefs429()"></header><div class="ai429-chips">${chips}</div><div id="ai429RefGrid" class="ref427-grid"></div></section><details class="advanced427-box"><summary>高级设置</summary><div class="form two"><div class="field"><label>置信度阈值</label><input id="ai429Threshold" class="input" value="0.45"></div><div class="field check"><label><input id="ai429Overwrite" type="checkbox"> 覆盖相同标签旧标注</label></div></div></details><div class="ailabel427-target">本次待处理 <b>${ids.length}</b> 张图片</div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick='submitAiLabel429(${JSON.stringify(ids)})'>开始AI标注</button></div></div>`,true);setTimeout(renderAiRefs429,30)};
  window.submitAiLabel429=async function(ids=[]){if(!ids.length)return toast('没有需要标注的图片');const body={image_ids:ids,labels_text:document.getElementById('ai429Labels')?.value||'',reference_image_ids:[...state.ai429RefSelected],threshold:+document.getElementById('ai429Threshold')?.value||.45,overwrite:!!document.getElementById('ai429Overwrite')?.checked,task_name:`AI自动标注-${new Date().toLocaleDateString()}`};try{const t=await api(`/api/v47/projects/${pid()}/ai-label-tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeModal();showTaskProgress427('label',t.id)}catch(e){toast(e.message||e)}};
  window.createAiLabel427=window.createAiLabel429;
  const oldReviewAi429=window.reviewAiLabel427;
  window.reviewAiLabel427=async function(id){const r=await api(`/api/v47/projects/${pid()}/ai-label-tasks/${id}/result`);state.ai429CandidateResult=r.result||{};return oldReviewAi429(id)};
  window.confirmAiLabel427=async function(id){try{const r=await api(`/api/v47/projects/${pid()}/ai-label-tasks/${id}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:[...state.v427AiConfirm]})});const cmap=new Map((state.ai429CandidateResult?.items||[]).map(x=>[String(x.image_id),x]));(r.applied_image_ids||[]).forEach(i=>{const img=(state.images||[]).find(x=>String(x.id)===String(i)),it=cmap.get(String(i));if(img&&it){img.annotated=(it.boxes||[]).length>0;img.box_count=(img.box_count||0)+(it.boxes||[]).length;img.labels=[...new Set([...(img.labels||[]),...(it.boxes||[]).map(b=>b.label).filter(Boolean)])]}});closeModal();if(state.page==='数据集')renderDatasets424();toast(`已确认 ${r.applied_images||0} 张，写入 ${r.boxes_added||0} 个框`)}catch(e){toast(e.message||e)}};

  // ---------- training from processed, labeled pool; internal split is automatic ----------
  function readyTargets429(){return(state.targets||[]).filter(t=>t.status==='ready')}
  function selectedTarget429(){return(state.targets||[]).find(x=>x.id===document.getElementById('tr429Target')?.value)}
  function selectedTrainAlg429(){const t=selectedTarget429(),k=document.getElementById('tr429Alg')?.value;return(t?.algorithms||[]).find(x=>x.key===k)}
  function pool429(){return(state.images||[]).filter(x=>processed429(x)&&x.annotated)}
  function cfg429(){return window.trainingConfigCanonical428()}
  window.startAlgorithmTraining429=function(aid){const a=(state.algorithms||[]).find(x=>x.id===aid);if(!a)return toast('算法不存在');const ts=readyTargets429();if(!ts.length)return toast('没有可用训练资源，请展开高级功能后配置训练资源');window.TrainingDraftRuntime?.update?.({algorithmId:String(aid),materialIds:[],testMaterialIds:[],splitMode:'random_test_from_training_pool',experimentPercent:20,validationPercent:20,newLabelCodes:[]});modal(`训练 · ${a.name}`,`<div class="train428-create train429-create"><section class="train428-identity"><div><span>算法持续迭代</span><h2>${esc(a.name)}</h2><p>${esc(algType429(a.algorithm_type))}${a.industry?` · ${esc(a.industry)}`:''}</p></div><div class="train428-version-rule"><span>新版本</span><b>训练结束自动生成</b><em>YYYYMMDDHHMMSS</em></div></section><div class="train428-grid"><section class="train428-panel"><header><b>1. 训练资源与训练算法</b></header><div class="form two"><div class="field"><label>训练资源</label><select id="tr429Target" class="select" onchange="trainTarget429()">${ts.map(t=>`<option value="${t.id}">${esc(t.name)} · ${t.framework==='paddle'?'Paddle':'Ultralytics'}</option>`).join('')}</select></div><div class="field"><label>训练算法</label><select id="tr429Alg" class="select" onchange="trainAlg429()"></select></div><div class="field"><label>关联算法</label><input class="input" value="${esc(a.name)}" readonly></div><div class="field"><label>任务优先级</label><input id="tr429Priority" class="input" type="number" min="1" max="999" step="1" value="50"><small>1 最高，数字越大优先级越低；相同数字按进入队列时间排序。</small></div></div></section><section class="train428-panel"><header><b>2. 本次训练素材</b></header><div class="train429-data-summary"><div><span>已处理且已标注</span><b id="tr429Count">${window.TrainingDraftRuntime?.materialIds?.().length||0} 张</b></div><div><span>标签</span><b id="tr429Labels">-</b></div><div><span>内部验证</span><b>自动留出 20%</b></div></div><div class="row"><button class="btn" onclick="openTrainPicker429()">选择素材</button><button class="btn" onclick="trainQuality429()">查看数据质量</button></div></section><section class="train428-panel train428-wide"><header class="row between"><b>3. 训练配置</b><button class="btn" onclick="openTrainSettings429()">配置设置</button></header><div class="train428-config-summary"><div><span>基础模型</span><b id="tr429Model">-</b></div><div><span>总轮数</span><b id="tr429Epoch">100</b></div><div><span>图片尺寸</span><b id="tr429Size">640</b></div><div><span>Batch</span><b id="tr429Batch">8</b></div><div><span>阶段检查</span><b id="tr429Gate">-</b></div><div><span>达标后转换</span><b id="tr429Convert">不自动转换</b></div></div></section></div><div id="tr429Estimate" class="estimate424"></div><div class="row end train428-footer"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="submitTrain429()">开始训练</button></div></div>`,true);setTimeout(trainTarget429,20);refreshTrain429()};
  window.startAlgorithmTraining423=window.startAlgorithmTraining429;
  window.trainTarget429=function(){const t=selectedTarget429(),sel=document.getElementById('tr429Alg');if(!sel)return;sel.innerHTML=(t?.algorithms||[]).map(x=>`<option value="${esc(x.key)}">${esc(x.name||x.short_name||x.key)}</option>`).join('')||'<option value="">当前资源没有可执行训练算法</option>';const c=cfg429();c.device=t?.type==='server'?'0':(t?.recommendation?.device||'cpu');window.TrainingDraftRuntime?.update?.({config:c,resource:{device:c.device}});trainAlg429()};
  window.trainAlg429=function(){const x=selectedTrainAlg429(),c=cfg429(),t=selectedTarget429();if(x){c.model=x.base_model||c.model;c.epochs=x.default_epochs||c.epochs;c.imgsz=x.default_imgsz||c.imgsz;c.batch=x.default_batch||c.batch}if(!c.model){const m=(t?.base_models||[])[0];c.model=m?.value||m?.label||''}window.TrainingDraftRuntime?.update?.({config:c,resource:{batch:c.batch}});refreshTrain429()};
  function selectedLabels429(){const ids=new Set(window.TrainingDraftRuntime?.materialIds?.()||[]),l=new Set();(state.images||[]).forEach(x=>{if(ids.has(x.id))(x.labels||[]).forEach(v=>l.add(v))});return[...l]}
  window.refreshTrain429=function(){const c=cfg429(),set=(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v};set('tr429Count',`${window.TrainingDraftRuntime?.materialIds?.().length||0} 张`);set('tr429Labels',selectedLabels429().join('、')||'-');set('tr429Model',String(c.model||'-').split(/[\\/]/).pop());set('tr429Epoch',c.epochs);set('tr429Size',c.imgsz);set('tr429Batch',c.batch);set('tr429Gate',`每 ${c.eval_interval||10} 轮 · ${c.val_max_samples>0?c.val_max_samples+' 张':'全部阶段试验样本'} · ${c.eval_metric||'map50'}`);set('tr429Convert',(c.auto_convert_targets||[]).map(x=>({ascend:'华为Atlas',rockchip:'瑞芯微',sophon:'算能'})[x]).join('、')||'不自动转换')};
  window.openTrainPicker429=function(){state.train429PickerLabels=new Set();state.train429PickerQ='';modal('选择训练素材',`<div class="picker429"><div><b>标签筛选</b><span>多选时，命中任意标签都会显示</span></div><div class="data426-chips" id="tr429Chips">${(state.labels||[]).map(l=>`<button class="data426-chip" data-l="${esc(l.code)}" onclick="toggleTrainLabel429('${esc(l.code)}')">${esc(l.display_name||l.code)}</button>`).join('')}</div><input id="tr429Q" class="input" placeholder="搜索素材名" oninput="renderTrainPicker429()"><div id="tr429Grid" class="picker429-grid"></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="closeModal();refreshTrain429()">确定</button></div></div>`,true);setTimeout(renderTrainPicker429,20)};
  window.toggleTrainLabel429=function(l){state.train429PickerLabels.has(l)?state.train429PickerLabels.delete(l):state.train429PickerLabels.add(l);document.querySelectorAll('#tr429Chips .data426-chip').forEach(b=>b.classList.toggle('on',state.train429PickerLabels.has(b.dataset.l)));renderTrainPicker429()};
  window.renderTrainPicker429=function(){const q=(document.getElementById('tr429Q')?.value||'').toLowerCase(),labs=[...state.train429PickerLabels],rows=pool429().filter(x=>(!q||String(x.filename).toLowerCase().includes(q))&&(!labs.length||labs.some(l=>(x.labels||[]).includes(l))));const g=document.getElementById('tr429Grid');if(g)g.innerHTML=rows.slice(0,300).map(x=>`<button class="${(window.TrainingDraftRuntime?.materialIds?.()||[]).includes(String(x.id))?'on':''}" onclick="toggleTrainImage429('${x.id}')"><img src="${x.url}" loading="lazy"><b>${esc(x.filename)}</b><span>${esc((x.labels||[]).join('、'))}</span></button>`).join('')||'<div class="empty">没有符合条件的已处理标注图片</div>'};
  window.toggleTrainImage429=function(id){window.TrainingDraftRuntime?.toggleMaterialId?.(id);renderTrainPicker429()};
  window.trainQuality429=async function(){const ids=window.TrainingDraftRuntime?.materialIds?.()||[];if(!ids.length)return toast('尚未选择素材');try{const r=await api(`/api/v44/projects/${pid()}/data-quality`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:ids})}),q=r.quality||{};modal('本次训练素材质量',`<div class="report429-kpis"><div><span>图片</span><b>${q.total_images??q.image_count??ids.length}</b></div><div><span>已标注</span><b>${q.annotated_images??'-'}</b></div><div><span>标签</span><b>${q.label_count??Object.keys(q.label_counts||{}).length}</b></div><div><span>标注框</span><b>${q.box_count??'-'}</b></div></div><div class="report429-card"><pre>${esc(JSON.stringify(q,null,2))}</pre></div>`,true)}catch(e){toast(e.message||e)}};
  window.openTrainSettings429=window.openTrainSettings428;
  function splitIds429(ids,seed=0){const arr=[...ids].sort((a,b)=>{const ha=[...String(a+seed)].reduce((s,c)=>(s*31+c.charCodeAt(0))>>>0,7),hb=[...String(b+seed)].reduce((s,c)=>(s*31+c.charCodeAt(0))>>>0,7);return ha-hb});const vn=Math.max(1,Math.min(arr.length-1,Math.round(arr.length*.2)));return{train:arr.slice(vn),val:arr.slice(0,vn)}}
  
  // routing is owned by the later stable render layer.
})();

// ===== v42.10.1 hotfixes: keep new algorithm cards and refresh new training summary =====
(() => {
  const _oldSaveTrainSettings429 = window.saveTrainSettings428;
  if (typeof _oldSaveTrainSettings429 === 'function') {
    window.saveTrainSettings428 = function(...args){
      const r = _oldSaveTrainSettings429.apply(this,args);
      setTimeout(() => { try { window.refreshTrain429?.(); } catch(e){} }, 20);
      return r;
    };
  }
})();

/* Classic direct training POST owners retired; TrainingSubmitRuntime owns canonical train-v3 submission. */
/* ============================================================
   v42.10 — resilient ZIP import + staged progress
   ============================================================ */
(()=>{
  const V410='42.24.0';
  const fmt410=s=>{s=Math.max(0,Number(s||0));if(s<60)return `${s.toFixed(s<10?1:0)}秒`;const m=Math.floor(s/60),r=Math.round(s%60);return `${m}分${r}秒`};
  const mb410=n=>(Number(n||0)/1024/1024).toFixed(1)+' MB';
  function errText410(xhr){let t=xhr?.responseText||'';try{const j=JSON.parse(t);t=j.detail||j.message||t}catch(e){}return String(t||`上传失败（HTTP ${xhr?.status||0}）`)}
  function set410(id,text){const e=document.getElementById(id);if(e)e.textContent=text}
  function width410(id,v){const e=document.getElementById(id);if(e)e.style.width=`${Math.max(0,Math.min(100,Number(v||0)))}%`}
  function uploadShell410(f){return `<div class="zip410">
    <section class="zip410-file"><div class="zip410-icon">ZIP</div><div><b>${esc(f.name)}</b><span>${mb410(f.size)} · 正在导入</span></div></section>
    <section class="zip410-steps">
      <article id="zip410StepUpload" class="active"><i>1</i><div><b>上传文件</b><span id="zip410UploadText">准备上传</span></div><em id="zip410UploadTime">0秒</em></article>
      <article id="zip410StepScan"><i>2</i><div><b>ZIP校验</b><span id="zip410ScanText">等待上传完成</span></div><em id="zip410ScanTime">-</em></article>
      <article id="zip410StepProcess"><i>3</i><div><b>解压与识别</b><span id="zip410ProcessText">等待开始</span></div><em id="zip410ProcessTime">-</em></article>
      <article id="zip410StepDone"><i>4</i><div><b>导入结果</b><span id="zip410DoneText">等待处理完成</span></div><em id="zip410TotalTime">-</em></article>
    </section>
    <section class="zip410-progress"><div><span id="zip410ProgressLabel">上传中</span><b id="zip410ProgressPct">0%</b></div><i><em id="zip410ProgressBar" style="width:0%"></em></i><p id="zip410ProgressSub">0 MB / ${mb410(f.size)}</p></section>
    <section id="zip410Result" class="zip410-result hidden"></section>
    <div class="row end"><button class="btn" onclick="closeModal()">关闭窗口</button></div>
  </div>`}
  function step410(id,cls){const e=document.getElementById(id);if(e){e.classList.remove('active','done','failed');if(cls)e.classList.add(cls)}}
  function xhrUpload410(url,fd,onProgress){return new Promise((resolve,reject)=>{const x=new XMLHttpRequest();x.open('POST',url,true);x.upload.onprogress=e=>{if(e.lengthComputable)onProgress?.(e.loaded,e.total)};x.onerror=()=>reject(new Error('网络连接中断，ZIP上传失败'));x.ontimeout=()=>reject(new Error('上传超时，请检查网络或压缩包大小'));x.onload=()=>{if(x.status>=200&&x.status<300){try{resolve(JSON.parse(x.responseText||'{}'))}catch(e){reject(new Error('服务器返回结果无法解析'))}}else reject(new Error(errText410(x)))};x.send(fd)})}
  async function pollZip410(jobId,started){let last=null;while(true){await new Promise(r=>setTimeout(r,650));let j;try{j=await api(`/api/v19/projects/${pid()}/import/jobs/${jobId}`)}catch(e){continue}last=j;step410('zip410StepProcess',j.status==='failed'?'failed':j.status==='done'?'done':'active');set410('zip410ProcessText',j.stage||j.message||'后台处理中');set410('zip410ProgressLabel',j.stage||'后台处理中');set410('zip410ProgressPct',`${Math.round(Number(j.progress||0))}%`);width410('zip410ProgressBar',j.progress||0);const ps=j.processing_seconds!=null?Number(j.processing_seconds):(performance.now()-started)/1000;set410('zip410ProcessTime',fmt410(ps));set410('zip410ProgressSub',j.message||`正在处理 ${j.processed||0} 张`);if(['done','failed'].includes(j.status))return j}}
  function result410(j,totalStart){const box=document.getElementById('zip410Result');if(!box)return;box.classList.remove('hidden');set410('zip410TotalTime',fmt410((performance.now()-totalStart)/1000));const r=j.report||{};if(j.status==='failed'){
      step410('zip410StepDone','failed');set410('zip410DoneText','导入失败');box.className='zip410-result failed';box.innerHTML=`<h3>导入失败</h3><p>${esc(j.error||j.message||'未知错误')}</p><div class="zip410-help"><b>请检查：</b><span>ZIP 是否损坏、是否包含支持的图片、图片与标注目录是否对应、YOLO/COCO/VOC 标注文件是否有效。</span></div><button class="btn" onclick="closeModal();setTimeout(openDataUpload426,30)">重新上传</button>`;return}
    step410('zip410StepDone','done');set410('zip410DoneText','导入完成');box.className='zip410-result success';const warns=(r.warnings||[]).map(x=>`<li>${esc(x)}</li>`).join('');box.innerHTML=`<h3>导入完成</h3><div class="zip410-kpis"><div><span>识别格式</span><b>${esc(r.detected_format||'原始图片')}</b></div><div><span>导入图片</span><b>${r.imported_images||0} 张</b></div><div><span>带标注图片</span><b>${r.annotated_images||0} 张</b></div><div><span>标注框</span><b>${r.boxes||0} 个</b></div></div>${warns?`<ul class="zip410-warn">${warns}</ul>`:''}<p>${(r.annotated_images||0)>0?'带有效标注的图片已直接归入“已处理”。':'本包未识别到有效标注，图片已进入“未处理”。'}</p>`}

  // 上传入口保持简单；ZIP 走新的分阶段任务接口。
  window.openDataUpload426=function(){modal('上传数据',`<div class="upload426-choices"><button onclick="chooseUploadImages426()"><b>上传图片</b><span>支持 JPG、PNG、WEBP，可一次选择多张</span></button><button onclick="chooseUploadZip426()"><b>上传 ZIP</b><span>支持原始图片或带 YOLO / COCO / VOC 标注的数据包</span></button></div><input id="up426Images" data-file426="1" class="hidden-file426" type="file" accept="image/*" multiple onchange="doUploadImages426(this)"><input id="up426Zip" data-file426="1" class="hidden-file426" type="file" accept=".zip,application/zip" onchange="doUploadZip426(this)">`,true)};
  window.doUploadZip426=async function(inp){const f=inp.files?.[0];if(!f)return;if(!/\.zip$/i.test(f.name)){toast('文件类型不支持，请选择 ZIP 压缩包');inp.value='';return}if(!f.size){toast('ZIP 文件为空，无法上传');inp.value='';return}const totalStart=performance.now(),uploadStart=performance.now();closeModal();setTimeout(()=>modal('ZIP 数据导入',uploadShell410(f),true),20);await new Promise(r=>setTimeout(r,60));const timer=setInterval(()=>set410('zip410UploadTime',fmt410((performance.now()-uploadStart)/1000)),200);try{const fd=new FormData();fd.append('file',f);const job=await xhrUpload410(`/api/v19/projects/${pid()}/datasets/default/import/jobs`,fd,(loaded,total)=>{const p=total?loaded/total*100:0;set410('zip410UploadText',`${mb410(loaded)} / ${mb410(total||f.size)}`);set410('zip410ProgressPct',`${Math.round(p)}%`);set410('zip410ProgressLabel','正在上传 ZIP');set410('zip410ProgressSub',`${mb410(loaded)} / ${mb410(total||f.size)}`);width410('zip410ProgressBar',p)});clearInterval(timer);step410('zip410StepUpload','done');set410('zip410UploadText','上传完成');set410('zip410UploadTime',fmt410(job.upload_seconds??((performance.now()-uploadStart)/1000)));step410('zip410StepScan','done');set410('zip410ScanText',`发现 ${job.image_count||0} 张图片 · ${esc((job.format_hints||[]).join('/')||'待识别')}`);set410('zip410ScanTime',fmt410(job.scan_seconds||0));set410('zip410ProgressLabel','ZIP校验完成');set410('zip410ProgressPct','0%');width410('zip410ProgressBar',0);set410('zip410ProgressSub',`压缩包 ${Number(job.file_size_mb||0).toFixed(1)} MB · 解压后约 ${Number(job.uncompressed_size_mb||0).toFixed(1)} MB`);
      let startedJob;try{startedJob=await api(`/api/v19/projects/${pid()}/import/jobs/${job.id}/start`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selected_paths:[]})})}catch(e){throw new Error(`后台导入无法启动：${e.message||e}`)}step410('zip410StepProcess','active');const done=await pollZip410(job.id,performance.now());result410(done,totalStart);if(done.status==='done'){await loadRelated();if(state.page==='数据集')renderDatasets424()}
    }catch(e){clearInterval(timer);step410('zip410StepUpload','failed');step410('zip410StepDone','failed');set410('zip410DoneText','上传或导入失败');set410('zip410ProgressLabel','失败');const box=document.getElementById('zip410Result');if(box){box.classList.remove('hidden');box.className='zip410-result failed';box.innerHTML=`<h3>上传失败</h3><p>${esc(e.message||String(e))}</p><button class="btn" onclick="closeModal();setTimeout(openDataUpload426,30)">重新上传</button>`}toast(e.message||e)}finally{inp.value=''}};
  // Keep visible version marker aligned.
})();

/* ============================================================
   v42.11 — responsive startup + upload task dock + annotation overlays
   ============================================================ */
(()=>{
  const V411='42.24.0';
  state.import411=state.import411||null;
  state.__extrasPromise=null;

  const fmtSec411=v=>{v=Math.max(0,Number(v||0));if(v<60)return `${Math.ceil(v)}秒`;const m=Math.floor(v/60),s=Math.ceil(v%60);return `${m}分${s?`${s}秒`:''}`};
  const bytes411=v=>{v=Number(v||0);if(v<1024)return `${v} B`;if(v<1024*1024)return `${(v/1024).toFixed(1)} KB`;return `${(v/1024/1024).toFixed(1)} MB`};
  const qualityKey411=()=>`cl_quality_411_${pid()||'none'}`;
  const invalidateQuality411=()=>{try{localStorage.removeItem(qualityKey411())}catch(e){}};

  // First paint only waits for core project/data objects. Heavy environment/model scans continue in background.
  const related411=loadRelated;
  async function extras411(){
    if(!state.project)return;
    const id=state.project.id,q=p=>p.catch(()=>null);
    const [opts,infer,rec,local]=await Promise.all([
      q(api(`/api/training_options?project_id=${id}`)),q(api('/api/v16/inference_envs')),
      q(api('/api/system/recommendation')),q(api('/api/local_models'))
    ]);
    state.targets=opts?.targets||[];state.inferenceEnvs=infer?.items||[];state.rec=rec;state.localModels=local?.items||[];
    renderSummary();
  }
  loadAll=async function(){
    await ensureWorkspace();
    await related411();
    if(!state.__extrasPromise) state.__extrasPromise=extras411().finally(()=>state.__extrasPromise=null);
  };

  // ---------- lightweight quality center: cached result first, explicit refresh recalculates ----------
  function qualityHtml411(r){
    const d=r?.dataset||{},a=r?.algorithm||{},scores=d.scores||{},as=a.scores||{};
    const fact=(k,v)=>`<div><span>${k}</span><b>${v??0}</b></div>`;
    return `<div class="quality424-shell"><div class="quality424-kpis"><div><span>数据质量</span><b>${d.overall_score||0}</b></div><div><span>素材数量</span><b>${d.images||0}</b></div><div><span>有效标注框</span><b>${d.box_count||0}</b></div><div><span>算法平均质量</span><b>${a.avg_score||0}</b></div><div><span>训练成功率</span><b>${a.train_success_rate||0}%</b></div></div><div class="quality411-actions"><span>质量指标采用缓存；数据变化后可手动刷新重新计算。</span><button class="btn primary" onclick="refreshQuality411()">刷新质量指标</button></div><div class="quality424-grid"><section class="panel quality424-card"><div class="panel-head"><div class="panel-title">数据质量</div></div><div class="panel-body quality424-radarbox">${typeof radar424==='function'?radar424(scores):''}<div class="quality424-facts">${fact('已标注',d.annotated_images)}${fact('标签数',d.label_count)}${fact('重复图片',d.duplicate_images)}${fact('低分辨率',d.low_resolution)}${fact('无效框',d.invalid_boxes)}${fact('数据体量',typeof fmtSize424==='function'?fmtSize424(d.total_size_bytes):d.total_size_bytes||0)}</div></div></section><section class="panel quality424-card"><div class="panel-head"><div class="panel-title">算法质量</div></div><div class="panel-body quality424-radarbox">${typeof radar424==='function'?radar424(as,'algorithm'):''}</div></section></div></div>`;
  }
  window.renderQualityCenter424=async function(){
    const view=document.getElementById('view');if(!view)return;
    let cached=null;try{cached=JSON.parse(localStorage.getItem(qualityKey411())||'null')}catch(e){}
    if(cached?.data){view.innerHTML=qualityHtml411(cached.data);return}
    view.innerHTML=`<section class="panel"><div class="panel-body quality411-empty"><b>质量指标尚未计算</b><span>不再阻塞平台首次启动。需要查看时再计算一次，之后直接读取缓存。</span><button class="btn primary" onclick="refreshQuality411()">开始计算质量指标</button></div></section>`;
  };
  window.refreshQuality411=async function(){
    const view=document.getElementById('view');if(view)view.innerHTML='<div class="quality411-loading"><b>正在计算质量指标</b><span>此计算只在您主动刷新时执行，其他页面不会被阻塞。</span></div>';
    try{const r=await api(`/api/v44/projects/${pid()}/quality-center`);try{localStorage.setItem(qualityKey411(),JSON.stringify({ts:Date.now(),data:r}))}catch(e){};if(state.page==='质量中心'&&view)view.innerHTML=qualityHtml411(r)}catch(e){if(view)view.innerHTML=`<div class="alert err">${esc(e.message||e)}</div>`}
  };

  // ---------- annotation overlays for cards / preview ----------
  function overlay411(x,limit=24){
    const w=Number(x.width||0),h=Number(x.height||0),boxes=(x.annotation_preview||[]).slice(0,limit);if(!w||!h||!boxes.length)return '';
    return `<div class="ann411-overlay">${boxes.map(b=>{const x1=Math.max(0,Math.min(w,Number(b.x1||0))),y1=Math.max(0,Math.min(h,Number(b.y1||0))),x2=Math.max(x1,Math.min(w,Number(b.x2||0))),y2=Math.max(y1,Math.min(h,Number(b.y2||0)));return `<i style="left:${x1/w*100}%;top:${y1/h*100}%;width:${(x2-x1)/w*100}%;height:${(y2-y1)/h*100}%"><em>${esc(b.label||'目标')}</em></i>`}).join('')}</div>`;
  }
  function dataCard411(x){
    const sel=state.data424Selected.has(x.id),ratio=(Number(x.width)>0&&Number(x.height)>0)?`${x.width}/${x.height}`:'16/10';
    return `<article class="data426-card data429-card ${sel?'selected':''}" onclick="selectCard429('${x.id}')"><div class="data426-pic data411-pic"><div class="data411-stage" style="aspect-ratio:${ratio}"><img src="${x.url}" loading="lazy" decoding="async">${overlay411(x)}</div><span class="data429-process ${processed429(x)?'ok':''}">${processed429(x)?'已处理':'未处理'}</span>${state.data426DeleteMode?`<label class="data426-check" onclick="event.stopPropagation()"><input type="checkbox" ${sel?'checked':''} onchange="selectData429('${x.id}',this.checked)"><i></i></label>`:''}</div><div class="data426-body"><div class="data426-title" title="${esc(x.filename)}">${esc(x.filename)}</div><div class="data426-meta"><span>${fmtSize424(x.size_bytes)}</span><span>${x.annotated?`已标注 · ${x.box_count||0}框`:'未标注'}</span><span>${esc(String(x.created_at||'').slice(0,10))}</span></div><div class="data426-tags">${(x.labels||[]).map(l=>`<span>${esc(l)}</span>`).join('')||'<em>无标签</em>'}</div><div class="data426-actions" onclick="event.stopPropagation()"><button class="btn mini" onclick="editData427('${x.id}')">编辑</button><button class="btn mini" onclick="previewData429('${x.id}')">详情</button><button class="btn mini primary" onclick="openAnnotation('${x.id}')">标注</button></div></div></article>`;
  }
  window.renderData429Cards=function(){
    const all=matchData429(),pages=Math.max(1,Math.ceil(all.length/state.data429PageSize));state.data429Page=Math.min(state.data429Page,pages);const st=(state.data429Page-1)*state.data429PageSize,rows=all.slice(st,st+state.data429PageSize);const g=document.getElementById('data429Grid');if(g)g.innerHTML=rows.map(dataCard411).join('')||'<div class="empty data426-empty">当前筛选条件下没有图片</div>';const c=document.getElementById('data429Count');if(c)c.textContent=`${all.length} 张`;const sc=document.getElementById('data429Selected');if(sc)sc.textContent=`已选 ${state.data424Selected.size} 张`;const p=document.getElementById('data429Pager');if(p)p.innerHTML=`<button class="btn mini" ${state.data429Page<=1?'disabled':''} onclick="dataPage429(-1)">上一页</button><span>${state.data429Page} / ${pages}</span><button class="btn mini" ${state.data429Page>=pages?'disabled':''} onclick="dataPage429(1)">下一页</button>`;
  };
  function previewHtml411(x,list,i){const ratio=(Number(x.width)>0&&Number(x.height)>0)?`${x.width}/${x.height}`:'16/10';return `<div class="data411-preview"><div class="data411-preview-stage" style="aspect-ratio:${ratio}"><img src="${x.url}">${overlay411(x,64)}</div><aside><h3>${esc(x.filename)}</h3><div><span>尺寸</span><b>${x.width||'-'} × ${x.height||'-'}</b></div><div><span>大小</span><b>${fmtSize424(x.size_bytes)}</b></div><div><span>标注</span><b>${x.annotated?`${x.box_count||0} 个框`:'未标注'}</b></div><div><span>标签</span><b>${esc((x.labels||[]).join('、')||'-')}</b></div><div class="row"><button class="btn" ${i<=0?'disabled':''} onclick="previewStep411(-1)">上一张</button><button class="btn" ${i>=list.length-1?'disabled':''} onclick="previewStep411(1)">下一张</button><button class="btn primary" onclick="openAnnotation('${x.id}')">编辑标注</button></div></aside></div>`}
  window.previewData429=function(id){const list=matchData429(),i=list.findIndex(x=>x.id===id);if(i<0)return;state.data426PreviewList=list;state.data426PreviewIndex=i;modal('图片预览',previewHtml411(list[i],list,i),true)};
  window.previewStep411=function(d){const list=state.data426PreviewList||[];let i=Math.max(0,Math.min(list.length-1,(state.data426PreviewIndex||0)+d));state.data426PreviewIndex=i;const layers=[...document.querySelectorAll('.v424-modal-layer')],top=layers[layers.length-1],body=top?.querySelector('.modal-body')||document.getElementById('modalBody');if(body&&list[i])window.ModalContentRuntime.replace(body,previewHtml411(list[i],list,i))};

  // Pointer based annotation editing is more stable than window-level mouse listeners, especially after zooming.
  bindAnnotationEvents=function(){
    const st=document.getElementById('annStage'),im=document.getElementById('annImg');if(!st||!im||st.dataset.bound411==='1')return;st.dataset.bound411='1';st.style.touchAction='none';st.style.cursor='crosshair';
    let mode='',start=null,temp=null,boxIndex=-1,orig=null,handle='',pointerId=null;
    const pos=e=>{const r=im.getBoundingClientRect(),size=imageSize();return{x:Math.max(0,Math.min(size.w,(e.clientX-r.left)/Math.max(1,r.width)*size.w)),y:Math.max(0,Math.min(size.h,(e.clientY-r.top)/Math.max(1,r.height)*size.h))}};
    const tempDraw=p=>{if(!start||!temp)return;const size=imageSize(),x1=Math.min(start.x,p.x),y1=Math.min(start.y,p.y),x2=Math.max(start.x,p.x),y2=Math.max(start.y,p.y);Object.assign(temp.style,{left:x1/size.w*100+'%',top:y1/size.h*100+'%',width:(x2-x1)/size.w*100+'%',height:(y2-y1)/size.h*100+'%'})};
    st.addEventListener('pointerdown',e=>{if(e.button!==0)return;pointerId=e.pointerId;try{st.setPointerCapture(pointerId)}catch(_){};const h=e.target.closest('.handle424'),bx=e.target.closest('.box424');start=pos(e);if(h&&bx){mode='resize';boxIndex=+bx.dataset.i;handle=h.dataset.h;orig={...state.ann.boxes[boxIndex]};pushHistory()}else if(bx){mode='move';boxIndex=+bx.dataset.i;orig={...state.ann.boxes[boxIndex]};state.activeBox=boxIndex;pushHistory()}else{mode='draw';temp=document.createElement('div');temp.className='drawBox';st.appendChild(temp);tempDraw(start)}e.preventDefault()});
    st.addEventListener('pointermove',e=>{if(!mode||pointerId!==e.pointerId||!start)return;const p=pos(e),size=imageSize();if(mode==='draw'){tempDraw(p);return}const b=state.ann.boxes[boxIndex];if(!b)return;if(mode==='move'){const dx=p.x-start.x,dy=p.y-start.y,w=orig.x2-orig.x1,h=orig.y2-orig.y1;b.x1=Math.max(0,Math.min(size.w-w,orig.x1+dx));b.y1=Math.max(0,Math.min(size.h-h,orig.y1+dy));b.x2=b.x1+w;b.y2=b.y1+h}else{let x1=orig.x1,y1=orig.y1,x2=orig.x2,y2=orig.y2;if(handle.includes('w'))x1=Math.min(p.x,x2-3);if(handle.includes('e'))x2=Math.max(p.x,x1+3);if(handle.includes('n'))y1=Math.min(p.y,y2-3);if(handle.includes('s'))y2=Math.max(p.y,y1+3);Object.assign(b,{x1,y1,x2,y2})}markDirty();drawBoxes();e.preventDefault()});
    const finish=e=>{if(!mode||pointerId!==e.pointerId||!start)return;const p=pos(e);if(mode==='draw'){const x1=Math.min(start.x,p.x),y1=Math.min(start.y,p.y),x2=Math.max(start.x,p.x),y2=Math.max(start.y,p.y);temp?.remove();if(x2-x1>5&&y2-y1>5){const l=(state.labels||[]).find(x=>x.class_id===state.activeLabel)||state.labels[0];if(l){pushHistory();state.ann.boxes.push({id:String(Date.now()).slice(-10),class_id:l.class_id,label:l.code,x1:Math.round(x1),y1:Math.round(y1),x2:Math.round(x2),y2:Math.round(y2)});state.activeBox=state.ann.boxes.length-1;markDirty()}}}else markDirty();try{st.releasePointerCapture(pointerId)}catch(_){};mode='';start=null;temp=null;boxIndex=-1;orig=null;pointerId=null;drawBoxes();renderAnnSide();e.preventDefault()};
    st.addEventListener('pointerup',finish);st.addEventListener('pointercancel',finish);
  };
  const saveAnn411=window.saveAnn;
  window.saveAnn=async function(silent=false){await saveAnn411(silent);const img=(state.images||[]).find(x=>x.id===state.activeImage?.id);if(img&&state.ann?.boxes){img.annotation_preview=state.ann.boxes.slice(0,32).map(b=>({class_id:b.class_id,label:b.label,x1:b.x1,y1:b.y1,x2:b.x2,y2:b.y2}));img.processing_status=state.ann.boxes.length?'processed':img.processing_status;invalidateQuality411()}};

  // ---------- image upload with actual browser upload progress / ETA ----------
  function uploadModal411(title,fileCount,totalBytes){return `<div class="up411"><section><b>${esc(title)}</b><span>${fileCount} 个文件 · ${bytes411(totalBytes)}</span></section><div class="up411-bar"><i id="up411Bar" style="width:0%"></i></div><div class="up411-line"><span id="up411Text">准备上传</span><b id="up411Pct">0%</b></div><div class="up411-line muted"><span>已用时间 <b id="up411Elapsed">0秒</b></span><span>预计剩余 <b id="up411Eta">计算中</b></span></div><div id="up411Result"></div></div>`}
  window.doUploadImages426=function(inp){
    const fs=[...(inp.files||[])];if(!fs.length)return;const total=fs.reduce((a,f)=>a+f.size,0),started=performance.now();closeModal();modal('图片上传',uploadModal411('正在上传图片',fs.length,total),true);const fd=new FormData();fs.forEach(f=>fd.append('files',f));fd.append('dataset_id','default');
    const xhr=new XMLHttpRequest();xhr.open('POST',`/api/projects/${pid()}/images`,true);let timer=setInterval(()=>{const e=document.getElementById('up411Elapsed');if(e)e.textContent=fmtSec411((performance.now()-started)/1000)},250);
    xhr.upload.onprogress=e=>{if(!e.lengthComputable)return;const p=e.loaded/e.total*100,elapsed=Math.max(.1,(performance.now()-started)/1000),speed=e.loaded/elapsed,eta=speed>0?(e.total-e.loaded)/speed:0;const bar=document.getElementById('up411Bar');if(bar)bar.style.width=p+'%';const pc=document.getElementById('up411Pct');if(pc)pc.textContent=Math.round(p)+'%';const tx=document.getElementById('up411Text');if(tx)tx.textContent=`${bytes411(e.loaded)} / ${bytes411(e.total)}`;const et=document.getElementById('up411Eta');if(et)et.textContent=fmtSec411(eta)};
    xhr.onerror=()=>{clearInterval(timer);const r=document.getElementById('up411Result');if(r)r.innerHTML='<div class="alert err">上传失败：网络连接异常。</div>'};
    xhr.onload=()=>{clearInterval(timer);let r={};try{r=JSON.parse(xhr.responseText||'{}')}catch(e){};const out=document.getElementById('up411Result');if(xhr.status<200||xhr.status>=300){if(out)out.innerHTML=`<div class="alert err">${esc(r.detail||xhr.responseText||'上传失败')}</div>`;return}const uploaded=r.uploaded||[];uploaded.forEach(x=>{x.split=x.split||'unassigned';x.annotated=!!x.annotated;x.labels=x.labels||[];x.box_count=x.box_count||0;x.processing_status=x.processing_status||'unprocessed'});state.images=[...uploaded,...(state.images||[])];invalidateQuality411();const failed=r.failed||[];if(out)out.innerHTML=`<div class="alert ok">成功上传 ${uploaded.length} 张${failed.length?`，失败 ${failed.length} 张`:''} · 用时 ${fmtSec411(r.elapsed_seconds||((performance.now()-started)/1000))}</div>${failed.map(x=>`<div class="alert warn">${esc(x.name)}：${esc(x.reason)}</div>`).join('')}<div class="row end"><button class="btn" onclick="closeModal()">关闭</button><button class="btn primary" onclick="closeModal();setPage('数据集')">查看数据</button></div>`;const bar=document.getElementById('up411Bar');if(bar)bar.style.width='100%';const pc=document.getElementById('up411Pct');if(pc)pc.textContent='100%';const et=document.getElementById('up411Eta');if(et)et.textContent='0秒';if(state.page==='数据集')renderDatasets424()};xhr.send(fd);inp.value='';
  };

  // ---------- ZIP task dock: upload/processing stays visible after minimize ----------
  function importDock411(){let d=document.getElementById('importDock411');if(!d){d=document.createElement('button');d.id='importDock411';d.className='import411-dock hidden';d.onclick=()=>restoreImport411();document.body.appendChild(d)}return d}
  function updateImportDock411(){const t=state.import411,d=importDock411();if(!t||!t.active){d.classList.add('hidden');return}d.classList.remove('hidden');d.innerHTML=`<i><em style="width:${Math.max(0,Math.min(100,t.progress||0))}%"></em></i><span><b>${esc(t.stage||'ZIP导入')}</b><small>${Math.round(t.progress||0)}% · 剩余 ${t.eta==null?'计算中':fmtSec411(t.eta)}</small></span><strong>展开</strong>`}
  function importShell411(){const t=state.import411||{};return `<div class="zip411"><section class="zip411-head"><div><b>${esc(t.fileName||'ZIP 数据导入')}</b><span>${bytes411(t.fileSize||0)}</span></div><button class="btn" onclick="minimizeImport411()">最小化到右下角</button></section><div class="zip411-main"><div class="zip411-progress"><div><span id="zip411Stage">${esc(t.stage||'准备上传')}</span><b id="zip411Pct">${Math.round(t.progress||0)}%</b></div><i><em id="zip411Bar" style="width:${Math.max(0,Math.min(100,t.progress||0))}%"></em></i><p id="zip411Msg">${esc(t.message||'')}</p></div><div class="zip411-times"><div><span>上传时间</span><b id="zip411UploadTime">${t.uploadSeconds==null?'-':fmtSec411(t.uploadSeconds)}</b></div><div><span>处理时间</span><b id="zip411ProcessTime">${t.processSeconds==null?'-':fmtSec411(t.processSeconds)}</b></div><div><span>预计剩余</span><b id="zip411Eta">${t.eta==null?'计算中':fmtSec411(t.eta)}</b></div></div><div id="zip411Result">${t.resultHtml||''}</div></div></div>`}
  function syncImportModal411(){const t=state.import411;if(!t)return;const s=document.getElementById('zip411Stage');if(s)s.textContent=t.stage||'';const p=document.getElementById('zip411Pct');if(p)p.textContent=Math.round(t.progress||0)+'%';const b=document.getElementById('zip411Bar');if(b)b.style.width=Math.max(0,Math.min(100,t.progress||0))+'%';const m=document.getElementById('zip411Msg');if(m)m.textContent=t.message||'';const u=document.getElementById('zip411UploadTime');if(u)u.textContent=t.uploadSeconds==null?'-':fmtSec411(t.uploadSeconds);const pr=document.getElementById('zip411ProcessTime');if(pr)pr.textContent=t.processSeconds==null?'-':fmtSec411(t.processSeconds);const e=document.getElementById('zip411Eta');if(e)e.textContent=t.eta==null?'计算中':fmtSec411(t.eta);const r=document.getElementById('zip411Result');if(r)r.innerHTML=t.resultHtml||'';updateImportDock411()}
  window.minimizeImport411=function(){closeModal();updateImportDock411();toast('ZIP 导入继续在后台执行')};
  window.restoreImport411=function(){if(!state.import411)return;modal('ZIP 数据导入',importShell411(),true);syncImportModal411()};
  function setImport411(patch){state.import411=Object.assign(state.import411||{},patch);syncImportModal411()}
  async function pollImport411(jobId){const start=performance.now();while(true){await new Promise(r=>setTimeout(r,450));let j;try{j=await api(`/api/v19/projects/${pid()}/import/jobs/${jobId}`)}catch(e){continue}let eta=j.eta_seconds;if(eta==null&&Number(j.progress)>2){const el=Math.max(.1,(performance.now()-start)/1000),p=Number(j.progress);eta=el/p*(100-p)}setImport411({stage:j.stage||'后台处理中',message:j.message||'',progress:Number(j.progress||0),processSeconds:j.processing_seconds??((performance.now()-start)/1000),eta});if(['done','failed'].includes(j.status))return j}}
  window.doUploadZip426=function(inp){
    const f=inp.files?.[0];if(!f)return;if(!/\.zip$/i.test(f.name)){toast('请选择 ZIP 压缩包');inp.value='';return}const totalStart=performance.now(),uploadStart=performance.now();state.import411={active:true,fileName:f.name,fileSize:f.size,stage:'正在上传 ZIP',message:'准备上传',progress:0,eta:null,resultHtml:''};closeModal();setTimeout(()=>{modal('ZIP 数据导入',importShell411(),true);syncImportModal411()},20);updateImportDock411();const fd=new FormData();fd.append('file',f);const xhr=new XMLHttpRequest();xhr.open('POST',`/api/v19/projects/${pid()}/datasets/default/import/jobs`,true);
    xhr.upload.onprogress=e=>{if(!e.lengthComputable)return;const p=e.loaded/e.total*35,elapsed=Math.max(.1,(performance.now()-uploadStart)/1000),speed=e.loaded/elapsed,eta=speed>0?(e.total-e.loaded)/speed:null;setImport411({stage:'正在上传 ZIP',message:`${bytes411(e.loaded)} / ${bytes411(e.total)}`,progress:p,eta,uploadSeconds:elapsed})};
    xhr.onerror=()=>setImport411({stage:'上传失败',progress:100,eta:0,resultHtml:'<div class="alert err">网络连接中断，ZIP 上传失败。</div>',active:true});
    xhr.onload=async()=>{let job={};try{job=JSON.parse(xhr.responseText||'{}')}catch(e){};if(xhr.status<200||xhr.status>=300){setImport411({stage:'上传失败',progress:100,eta:0,resultHtml:`<div class="alert err">${esc(job.detail||xhr.responseText||'上传失败')}</div>`});return}setImport411({jobId:job.id,stage:'ZIP校验完成',message:`发现 ${job.image_count||0} 张图片 · ${esc((job.format_hints||[]).join('/')||'待识别')}`,progress:38,uploadSeconds:job.upload_seconds,processSeconds:job.scan_seconds,eta:null});try{await api(`/api/v19/projects/${pid()}/import/jobs/${job.id}/start`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({selected_paths:[]})});const done=await pollImport411(job.id),r=done.report||{};if(done.status==='done'){const warns=(r.warnings||[]).map(x=>`<li>${esc(x)}</li>`).join('');setImport411({stage:'导入完成',message:`${r.imported_images||0} 张图片 · ${r.boxes||0} 个框`,progress:100,eta:0,processSeconds:done.processing_seconds,resultHtml:`<div class="alert ok"><b>导入完成</b>：${r.imported_images||0} 张图片，其中 ${r.annotated_images||0} 张带标注，${r.boxes||0} 个框。</div>${warns?`<ul class="zip410-warn">${warns}</ul>`:''}<div class="row end"><button class="btn" onclick="state.import411.active=false;updateImportDock411();closeModal()">关闭</button><button class="btn primary" onclick="state.import411.active=false;updateImportDock411();closeModal();setPage('数据集')">查看数据</button></div>`});window.completeZipImportReview412?.(job.id);invalidateQuality411();await window.refreshLabels414?.(false);if(state.page==='数据集')await window.reloadMaterialPage61?.()}else setImport411({stage:'导入失败',progress:100,eta:0,resultHtml:`<div class="alert err">${esc(done.error||done.message||'导入失败')}</div>`})}catch(e){setImport411({stage:'导入失败',progress:100,eta:0,resultHtml:`<div class="alert err">${esc(e.message||e)}</div>`})}};xhr.send(fd);inp.value='';
  };
  // Run the one initial load only after every version override above has been installed.
  queueMicrotask(()=>{if(window.__clInit)window.__clInit()});
})();

/* ============================================================
   v42.12 — stability consolidation: fast core, import review, stable data/algorithm pages
   ============================================================ */
(()=>{
  const V412='42.24.0';
  state.data412Tab=state.data412Tab||'processed';
  state.data412Labels=state.data412Labels||new Set();
  state.data412Page=state.data412Page||1;
  state.data412PageSize=48;
  state.data412DeleteMode=false;
  state.data412Selected=state.data412Selected||new Set();
  state.import412Selected=state.import412Selected||new Set();
  state.__extras412=null;

  const isProcessed412=x=>!!(x?.annotated||x?.processing_status==='processed'||x?.cleaned_at||x?.clean_skipped);
  const activeJob412=a=>(state.jobs||[]).find(j=>(j.asset_algorithm_id===a.id||j.algorithm_asset_id===a.id)&&['queued','running','paused','waiting','pending'].includes(j.status));
  const algType412=id=>({yolo_ultralytics:'YOLO / Ultralytics',paddle_detection:'PaddleDetection',opencv:'OpenCV 传统视觉',mmdetection:'MMDetection',custom_python:'自定义 Python / 其他'})[id]||id||'算法';
  const pct412=v=>{if(v==null||v===''||Number.isNaN(Number(v)))return '-';let n=Number(v);if(n<=1)n*=100;return n.toFixed(1)+'%'};
  const versionMetric412=v=>{const r=v?.report||{},m=r.metrics||{};return m['metrics/mAP50(B)']??m.map50??m.mAP50??v?.accuracy??null};
  const dt412=v=>v?String(v).replace('T',' ').replace('Z','').slice(0,19):'-';

  // Core first paint: do not wait for model scans / quality / publish / inference lists.
  window.loadCore412=async function(){
    await ensureWorkspace(); if(!state.project)return;
    const id=state.project.id;
    const snapshot=await api(`/api/v53/bootstrap/snapshot?preferred_project_id=${encodeURIComponent(id)}&refresh=true`);
    state.datasets=snapshot.datasets||[];state.labels=snapshot.labels||[];state.algorithms=snapshot.algorithms||[];state.jobs=snapshot.jobs||[];
    state.materialSummary61=snapshot.material_summary;state.annotationSummary61=snapshot.annotation_summary;
    if(!state.datasets.find(d=>d.id===state.datasetId))state.datasetId=state.datasets[0]?.id||'default';
    const full=window.PlatformCore?.materialPaging?.requiresFullMaterialPool(state.page)||false;
    if(window.__materialPaging61)window.__materialPaging61.mode=full?'full':'paged';
    if(full)state.images=await api(`/api/projects/${id}/images`);
    else if(state.page==='数据集'&&window.reloadMaterialPage61)await window.reloadMaterialPage61();
    else if(state.page==='数据集'||state.page==='素材接入')state.images=(await api(`/api/v61/projects/${id}/materials?limit=48`)).items||[];
  };
  async function pollAnnotationIndex412(){
    if(!state.project||state.__annPoll412)return; state.__annPoll412=true; const id=state.project.id;
    try{
      for(let i=0;i<90;i++){
        const st=await safe(api(`/api/v52/projects/${id}/annotation-index/status`));
        if(!st||(!st.running&&!st.pending))break;
        await new Promise(r=>setTimeout(r,i<8?350:900));
      }
      const st=await safe(api(`/api/v52/projects/${id}/annotation-index/status`));
      if(st&&!st.pending){const imgs=await safe(api(`/api/projects/${id}/images`));if(Array.isArray(imgs)){state.images=imgs;if(state.page==='数据集')renderDatasets424();try{renderSummary()}catch(e){}}}
    }finally{state.__annPoll412=false}
  }
  async function extras412(){
    if(!state.project)return;const id=state.project.id,page=state.page,tasks=[];
    const load=(key,url,field)=>tasks.push(api(url).then(value=>{state[key]=field?(value?.[field]||[]):value}));
    if(['训练任务','训练资源','自动迭代'].includes(page))load('targets',`/api/training_options?project_id=${id}`,'targets');
    if(['算法列表','训练任务','自动迭代'].includes(page))load('jobs',`/api/projects/${id}/jobs`);
    if(['测试发布','部署测试'].includes(page)){
      load('pending',`/api/v12/projects/${id}/publish/pending`,'items');
      load('testModels',`/api/v12/projects/${id}/test_models`,'items');
      load('inferenceEnvs','/api/v16/inference_envs','items');
    }
    if(['训练任务','测试发布','部署转换','部署产物'].includes(page))load('models',`/api/projects/${id}/models`);
    if(['模型配置','自动标注','自动标注及清洗'].includes(page))load('modelConfigs','/api/v35/model-configs','items');
    const results=await Promise.allSettled(tasks);for(const result of results)if(result.status==='rejected')toast(result.reason?.message||String(result.reason));
    // Annotation JSON fallback is per image; ordinary refresh never starts a project scan.
  }
  window.loadPageExtras413=extras412;
  window.refreshCurrentPage413=async function(){await window.loadCore412();await extras412();if(['部署转换','部署产物','部署资源'].includes(state.page)&&typeof loadDeployData==='function')await loadDeployData(true)};
  loadAll=window.refreshCurrentPage413;
  window.__clInit=async function(){const view=document.getElementById('view');if(view)view.innerHTML='<div class="boot412"><i></i><b>正在读取算法与素材</b><span>先加载核心数据，其余资源后台补齐</span></div>';await window.loadCore412();render();state.uiReady=true;if(!state.__extras412)state.__extras412=extras412().finally(()=>state.__extras412=null)};

  // -------- stable algorithm renderer --------
  function verRow412(a,v){const can=!!String(v.stored_path||'').trim();return `<div class="alg428-version-row"><div class="alg428-version-id"><i></i><div><b>${esc(v.version_name||'-')}</b><span>${dt412(v.finished_at||v.created_at)}</span></div></div><div class="alg428-version-status"><span>训练状态</span><b>${esc((typeof status429==='function'?status429(v.training_status||v.status||'done'):(v.training_status||v.status||'已完成')))}</b></div><div class="alg428-version-accuracy"><span>正确率 · mAP50</span><b>${pct412(versionMetric412(v))}</b></div><div class="alg428-version-model"><span>训练成果</span><b>${can?esc(v.model_name||'模型文件'):'无模型文件'}</b></div><div class="alg428-version-actions"><button class="btn mini" onclick="event.stopPropagation();openVersionReport429('${a.id}','${v.id}')">训练报告</button><button class="btn mini primary" onclick="event.stopPropagation();openVersionConvert428('${a.id}','${v.id}')">转换</button>${can?`<a class="btn mini" onclick="event.stopPropagation()" href="/api/v12/projects/${pid()}/algorithms/${a.id}/versions/${v.id}/download">下载模型</a>`:''}</div></div>`}
  window.renderAlg412=function(){const box=document.getElementById('alg412List');if(!box)return;const q=(document.getElementById('alg412Q')?.value||'').trim().toLowerCase(),ind=document.getElementById('alg412Industry')?.value||'all',typ=document.getElementById('alg412Type')?.value||'all';const rows=(state.algorithms||[]).filter(a=>(!q||`${a.name} ${a.remark||''} ${a.industry||''} ${a.algorithm_type||''}`.toLowerCase().includes(q))&&(ind==='all'||a.industry===ind)&&(typ==='all'||a.algorithm_type===typ));box.innerHTML=rows.map(a=>{const vs=a.versions||[],latest=vs[0],open=!!state.alg428Expanded?.[a.id],run=activeJob412(a);return `<article class="alg428-card ${open?'open':''}"><div class="alg428-main" onclick="toggleAlgorithm412('${a.id}')"><div class="alg428-logo">${esc((a.name||'算').slice(0,1))}</div><div class="alg428-info"><div class="alg428-title"><b>${esc(a.name)}</b><span>${esc(algType412(a.algorithm_type))}</span>${a.industry?`<em>${esc(a.industry)}</em>`:''}</div><p>${esc(a.remark||'')}</p><div class="alg428-meta"><span>训练次数 <b>${(state.jobs||[]).filter(j=>j.asset_algorithm_id===a.id||j.algorithm_asset_id===a.id).length}</b></span><span>版本 <b>${vs.length}</b></span><span>最新正确率 <b>${pct412(versionMetric412(latest))}</b></span></div></div><div class="alg428-state">${run?`<span class="alg428-running">${esc(run.status_text||run.status)}</span><small>${esc(run.execution_resource?.name||run.server_name||'训练资源')}</small>`:`<span class="alg429-last">${latest?'最新 '+esc(latest.version_name):'尚未训练'}</span>`}</div><div class="alg428-actions" onclick="event.stopPropagation()"><button class="btn mini" onclick="viewAlgorithm429('${a.id}')">详情</button><button class="btn mini" onclick="algorithmReport429('${a.id}')">综合报告</button><button class="btn mini" onclick="editAlgorithm423('${a.id}')">编辑</button><button class="btn mini primary" onclick="startAlgorithmTraining429('${a.id}')">训练</button><button class="btn mini danger" onclick="delAlgorithm('${a.id}')">删除</button><i class="alg428-chevron">⌄</i></div></div>${open?`<div class="alg428-versions"><div class="alg428-version-head"><b>迭代版本</b><span>训练完成时间即版本号</span></div>${vs.length?vs.map(v=>verRow412(a,v)).join(''):'<div class="empty alg428-empty">暂无版本，点击“训练”开始第一次迭代</div>'}</div>`:''}</article>`}).join('')||'<div class="empty">暂无算法</div>'};
  window.renderAlgorithms423=function(){const inds=[...new Set((state.algorithms||[]).map(a=>a.industry).filter(Boolean))].sort();document.getElementById('view').innerHTML=`<section class="alg428-shell"><div class="alg428-toolbar"><div class="filter423"><input id="alg412Q" class="input" placeholder="搜索算法" oninput="renderAlg412()"><select id="alg412Industry" class="select" onchange="renderAlg412()"><option value="all">全部行业场景</option>${inds.map(x=>`<option>${esc(x)}</option>`).join('')}</select><select id="alg412Type" class="select" onchange="renderAlg412()"><option value="all">全部算法类型</option><option value="yolo_ultralytics">YOLO / Ultralytics</option><option value="paddle_detection">PaddleDetection</option><option value="opencv">OpenCV 传统视觉</option><option value="mmdetection">MMDetection</option><option value="custom_python">自定义 Python / 其他</option></select></div><button class="btn primary" type="button" data-action="algorithm.create">＋ 新建算法</button></div><div id="alg412List" class="alg428-list"></div></section>`;renderAlg412()};
  window.toggleAlgorithm412=async function(id){state.alg428Expanded=state.alg428Expanded||{};state.alg428Expanded[id]=!state.alg428Expanded[id];if(state.alg428Expanded[id]){const r=await safe(api(`/api/v12/projects/${pid()}/algorithms`));if(r?.items)state.algorithms=r.items}renderAlg412()};
  window.toggleAlgorithm428=window.toggleAlgorithm412;

  // -------- data pool: raw vs ready are orthogonal to annotation --------
  function actualLabels412(){return(state.labels||[]).filter(l=>l?.code&&l.status!=='disabled'&&l.status!=='inactive').map(l=>l.code)}
  function displayLabel412(code){const value=String(code||'').trim(),item=(state.labels||[]).find(l=>String(l?.code||'')===value),name=String(item?.display_name||item?.display_name_zh||'').trim();return name&&name!==value?`${value} · ${name}`:value}
  function dataRows412(){const tab=state.data412Tab,q=(document.getElementById('data412Q')?.value||'').trim().toLowerCase(),ann=document.getElementById('data412Ann')?.value||'all',labs=[...state.data412Labels];return(state.images||[]).filter(x=>{const proc=isProcessed412(x);if(tab==='unprocessed'&&x.annotation_index_pending)return false;if(tab==='unprocessed'?(proc||x.annotated):!proc)return false;if(q&&!String(x.filename||'').toLowerCase().includes(q))return false;if(tab==='processed'&&ann==='marked'&&!x.annotated)return false;if(tab==='processed'&&ann==='unmarked'&&x.annotated)return false;if(tab==='processed'&&labs.length&&!labs.some(l=>(x.labels||[]).includes(l)))return false;return true})}
  function ov412(x){if(!x.annotated)return'';const w=Number(x.width||0),h=Number(x.height||0);if(!w||!h)return'';return (x.annotation_preview||[]).slice(0,24).map(b=>{const l=100*Number(b.x1||0)/w,t=100*Number(b.y1||0)/h,r=100*Number(b.x2||0)/w,bt=100*Number(b.y2||0)/h;return `<i class="data412-box" style="left:${l}%;top:${t}%;width:${Math.max(.2,r-l)}%;height:${Math.max(.2,bt-t)}%"><em>${esc(displayLabel412(b.label))}</em></i>`}).join('')}
  function card412(x){const sel=state.data412Selected.has(x.id),raw=state.data412Tab==='unprocessed';return `<article class="data426-card data412-card ${sel?'selected':''}" onclick="${state.data412DeleteMode?`toggleData412('${x.id}')`:`previewData429('${x.id}')`}"><div class="data426-pic data411-pic"><div class="data411-stage" style="aspect-ratio:${Math.max(.3,Math.min(3,(x.width||16)/(x.height||9)))}"><img src="${x.url}" loading="lazy" decoding="async">${raw?'':ov412(x)}</div><span class="data429-process ${raw?'':'ok'}">${raw?'未处理':'已处理'}</span>${state.data412DeleteMode?`<label class="data426-check" onclick="event.stopPropagation()"><input type="checkbox" ${sel?'checked':''} onchange="setData412('${x.id}',this.checked)"><i></i></label>`:''}</div><div class="data426-body"><div class="data426-title">${esc(x.filename)}</div><div class="data426-meta"><span>${typeof fmtSize424==='function'?fmtSize424(x.size_bytes):''}</span><span>${raw?'尚未完成清洗决策':(x.annotated?`已标注 · ${x.box_count||0}框`:'待标注')}</span></div>${raw?'':`<div class="data426-tags">${(x.labels||[]).map(l=>`<span>${esc(displayLabel412(l))}</span>`).join('')||'<em>暂无标签</em>'}</div>`}<div class="data426-actions" onclick="event.stopPropagation()"><button class="btn mini" onclick="previewData429('${x.id}')">详情</button>${raw?`<button class="btn mini" onclick="markReady412(['${x.id}'])">无需清洗</button><button class="btn mini primary" onclick="createClean427({image_ids:['${x.id}']})">清洗</button>`:`<button class="btn mini primary" onclick="openAnnotation('${x.id}')">${x.annotated?'编辑标注':'标注'}</button>`}</div></div></article>`}
  window.renderData412Cards=function(){const all=dataRows412(),pages=Math.max(1,Math.ceil(all.length/state.data412PageSize));state.data412Page=Math.min(Math.max(1,state.data412Page),pages);const st=(state.data412Page-1)*state.data412PageSize,rows=all.slice(st,st+state.data412PageSize);const g=document.getElementById('data412Grid');if(g)g.innerHTML=rows.map(card412).join('')||'<div class="empty data426-empty">当前没有素材</div>';const c=document.getElementById('data412Count');if(c)c.textContent=`${all.length} 张`;const s=document.getElementById('data412SelCount');if(s)s.textContent=`已选 ${state.data412Selected.size} 张`;const p=document.getElementById('data412Pager');if(p)p.innerHTML=`<button class="btn mini" ${state.data412Page<=1?'disabled':''} onclick="state.data412Page--;renderData412Cards()">上一页</button><span>${state.data412Page} / ${pages}</span><button class="btn mini" ${state.data412Page>=pages?'disabled':''} onclick="state.data412Page++;renderData412Cards()">下一页</button>`}
  window.renderDatasets424=function(){const pendingIndex=(state.images||[]).filter(x=>x.annotation_index_pending).length,raw=(state.images||[]).filter(x=>!x.annotation_index_pending&&!isProcessed412(x)&&!x.annotated).length,ready=(state.images||[]).filter(isProcessed412).length,labs=actualLabels412();document.getElementById('view').innerHTML=`<section class="data426-shell">${pendingIndex?`<div class="data412-indexing"><i></i><span>正在后台整理 ${pendingIndex} 张历史素材的标注索引，页面可继续操作，完成后自动刷新。</span></div>`:''}<div class="data426-head"><div class="data424-tabs"><button class="${state.data412Tab==='unprocessed'?'on':''}" onclick="setData412Tab('unprocessed')"><span>未处理</span><b>${raw}</b></button><button class="${state.data412Tab==='processed'?'on':''}" onclick="setData412Tab('processed')"><span>已处理</span><b>${ready}</b></button></div><div class="row"><button class="btn primary" onclick="openDataUpload426()">上传</button>${state.data412Tab==='unprocessed'?`<button class="btn" onclick="createClean427({image_ids:dataRows412().map(x=>x.id)})">清洗当前素材</button><button class="btn" onclick="markReady412(dataRows412().map(x=>x.id))">当前素材无需清洗</button>`:''}<button class="btn danger" onclick="toggleDelete412()">${state.data412DeleteMode?'取消删除':'删除'}</button></div></div><section class="panel data426-panel">${state.data412Tab==='processed'?`<div class="data426-filtertop"><div class="data426-filter-title"><b>标签筛选</b><span>多选时，只要命中任意一个标签即可</span></div><div class="data426-chips"><button class="data426-chip clear ${state.data412Labels.size?'':'on'}" onclick="clearLabels412()">全部</button>${labs.map(l=>`<button class="data426-chip ${state.data412Labels.has(l)?'on':''}" onclick="toggleLabel412('${esc(l)}')">${esc(l)}</button>`).join('')}</div></div>`:''}<div class="data426-toolbar"><input id="data412Q" class="input" placeholder="搜索素材名称" oninput="state.data412Page=1;renderData412Cards()">${state.data412Tab==='processed'?`<select id="data412Ann" class="select compact427" onchange="state.data412Page=1;renderData412Cards()"><option value="all">全部标注</option><option value="marked">已标注</option><option value="unmarked">待标注</option></select>`:''}<span id="data412Count"></span>${state.data412DeleteMode?`<b id="data412SelCount">已选 ${state.data412Selected.size} 张</b><button class="btn" onclick="selectAll412()">全选当前</button><button class="btn" onclick="invert412()">反选当前</button><button class="btn danger" onclick="batchDelete412()">删除已选</button>`:''}</div><div id="data412Grid" class="data426-grid"></div><div id="data412Pager" class="data426-pager"></div></section></section>`;renderData412Cards()};
  window.setData412Tab=t=>{state.data412Tab=t;state.data412Labels.clear();state.data412Selected.clear();state.data412DeleteMode=false;state.data412Page=1;renderDatasets424()};
  window.toggleLabel412=l=>{state.data412Labels.has(l)?state.data412Labels.delete(l):state.data412Labels.add(l);state.data412Page=1;renderDatasets424()};
  window.clearLabels412=()=>{state.data412Labels.clear();state.data412Page=1;renderDatasets424()};
  window.toggleDelete412=()=>{state.data412DeleteMode=!state.data412DeleteMode;state.data412Selected.clear();renderDatasets424()};
  window.setData412=(id,on)=>{on?state.data412Selected.add(id):state.data412Selected.delete(id);renderData412Cards()};
  window.toggleData412=id=>{state.data412Selected.has(id)?state.data412Selected.delete(id):state.data412Selected.add(id);renderData412Cards()};
  window.selectAll412=()=>{dataRows412().forEach(x=>state.data412Selected.add(x.id));renderData412Cards()};
  window.invert412=()=>{dataRows412().forEach(x=>state.data412Selected.has(x.id)?state.data412Selected.delete(x.id):state.data412Selected.add(x.id));renderData412Cards()};
  window.batchDelete412=async()=>{const ids=[...state.data412Selected];if(!ids.length)return toast('请选择要删除的素材');if(!confirm(`确认删除 ${ids.length} 张素材？对应图片和标注会一起删除。`))return;const r=await api(`/api/v46/projects/${pid()}/images/batch-delete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:ids})});const deleted=new Set((r.deleted_images||[]).map(x=>String(typeof x==='object'?x.id:x)));state.images=(state.images||[]).filter(x=>!deleted.has(String(x.id)));state.data412Selected.clear();state.data412DeleteMode=false;renderDatasets424();const failed=(r.failed_items||[]).length;toast(failed?`已删除 ${deleted.size} 张，${failed} 张失败并已保留`:`已删除 ${deleted.size} 张`)};
  window.markReady412=async ids=>{ids=(ids||[]).filter(Boolean);if(!ids.length)return toast('当前没有可操作素材');const r=await api(`/api/v52/projects/${pid()}/images/mark-ready`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:ids})});const set=new Set(r.image_ids||ids);(state.images||[]).forEach(x=>{if(set.has(String(x.id))||set.has(x.id)){x.processing_status='processed';x.clean_skipped=true}});if(state.page==='数据集')renderDatasets424();toast(`已确认 ${r.changed||ids.length} 张无需清洗`)};

  window.previewData429=function(id){const list=dataRows412(),idx=list.findIndex(x=>String(x.id)===String(id)),x=idx>=0?list[idx]:(state.images||[]).find(y=>String(y.id)===String(id));if(!x)return;state.data426PreviewList=list.length?list:[x];state.data426PreviewIndex=Math.max(0,idx);const raw=!isProcessed412(x)&&!x.annotated;const body=`<div class="data429-preview"><div class="data412-previewstage"><img src="${x.url}">${raw?'':ov412(x)}</div><aside><h2>${esc(x.filename)}</h2><dl><dt>处理状态</dt><dd>${raw?'未处理':'已处理'}</dd><dt>标注状态</dt><dd>${x.annotated?'已标注':'待标注'}</dd>${raw?'':`<dt>标签</dt><dd>${esc((x.labels||[]).map(displayLabel412).join('、')||'-')}</dd>`}<dt>尺寸</dt><dd>${x.width||'-'} × ${x.height||'-'}</dd><dt>时间</dt><dd>${dt412(x.created_at)}</dd></dl><div class="row">${raw?`<button class="btn" onclick="markReady412(['${x.id}'])">无需清洗</button><button class="btn primary" onclick="closeModal();createClean427({image_ids:['${x.id}']})">清洗</button>`:`<button class="btn primary" onclick="openAnnotation('${x.id}')">${x.annotated?'编辑标注':'标注'}</button>`}</div></aside></div>`;modal('图片详情',body,true)};

  // -------- import review + label remap --------
  function reviewRows412(){const ids=state.import412?.image_ids||[];const set=new Set(ids.map(String));return(state.images||[]).filter(x=>set.has(String(x.id)))}
  function reviewHtml412(){const r=state.import412||{},rows=reviewRows412(),counts=r.label_box_counts||{},labels=Object.entries(counts);return `<div class="import412"><section class="import412-head"><div><span>本次导入整理</span><h2>${esc(r.file_name||'导入素材')}</h2><p>${rows.length} 张图片 · ${rows.filter(x=>x.annotated).length} 张带标注</p></div><div class="row"><button class="btn" onclick="selectImportAll412()">全选</button><button class="btn" onclick="invertImport412()">反选</button></div></section>${labels.length?`<section class="import412-labels"><header><b>统一调整本次导入标签</b><span>例如 class_0 实际代表 fire，可只改本次导入素材，不影响其他批次。</span></header>${labels.map(([l,n])=>`<div class="import412-labelrow"><div><b>${esc(l)}</b><span>${n} 个框</span></div><span>→</span><input id="map412_${encodeURIComponent(l)}" class="input" value="${esc(l)}"><button class="btn primary" onclick="remapImport412(decodeURIComponent('${encodeURIComponent(l)}'),'map412_${encodeURIComponent(l)}')">统一改名</button></div>`).join('')}</section>`:''}<section class="import412-grid">${rows.slice(0,160).map(x=>`<label class="import412-card ${state.import412Selected.has(String(x.id))?'on':''}"><input type="checkbox" ${state.import412Selected.has(String(x.id))?'checked':''} onchange="toggleImport412('${x.id}',this.checked)"><img src="${x.url}" loading="lazy"><b>${esc(x.filename)}</b><span>${x.annotated?esc((x.labels||[]).join('、')||'已标注'):'待标注'}</span></label>`).join('')}</section><section class="import412-decision"><div><b>这些素材是否需要清洗？</b><span>带标注素材不会进入“未处理”；无标注素材如果确认无需清洗，也会直接进入“已处理 · 待标注”。</span></div><div class="row"><button class="btn" onclick="importNoClean412()">无需清洗，直接使用</button><button class="btn primary" onclick="importClean412()">需要清洗</button></div></section></div>`}
  window.showImportReview412=async jobId=>{await window.loadCore412();const rr=await api(`/api/v52/projects/${pid()}/import/jobs/${jobId}/review`);state.import412={job_id:jobId,file_name:rr.job?.file_name||'',image_ids:rr.image_ids||[],label_box_counts:rr.label_box_counts||{}};state.import412Selected=new Set((rr.image_ids||[]).map(String));modal('本次导入素材',reviewHtml412(),true)};
  window.toggleImport412=(id,on)=>{on?state.import412Selected.add(String(id)):state.import412Selected.delete(String(id));const b=document.querySelector(`.import412-card input[onchange*="${id}"]`);if(b)b.closest('.import412-card')?.classList.toggle('on',on)};
  window.selectImportAll412=()=>{(state.import412?.image_ids||[]).forEach(id=>state.import412Selected.add(String(id)));const body=[...document.querySelectorAll('.v424-modal-layer .modal-body')].at(-1)||document.getElementById('modalBody');if(body)window.ModalContentRuntime.replace(body,reviewHtml412())};
  window.invertImport412=()=>{(state.import412?.image_ids||[]).forEach(id=>state.import412Selected.has(String(id))?state.import412Selected.delete(String(id)):state.import412Selected.add(String(id)));const body=[...document.querySelectorAll('.v424-modal-layer .modal-body')].at(-1)||document.getElementById('modalBody');if(body)window.ModalContentRuntime.replace(body,reviewHtml412())};
  window.remapImport412=async(source,inputId)=>{const target=document.getElementById(inputId)?.value.trim();if(!target)return toast('请输入新标签名');const ids=[...state.import412Selected];if(!ids.length)return toast('请选择本次导入素材');const r=await api(`/api/v52/projects/${pid()}/labels/remap`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:ids,source_label:source,target_label:target})});await window.loadCore412();const rr=await api(`/api/v52/projects/${pid()}/import/jobs/${state.import412.job_id}/review`);state.import412.label_box_counts=rr.label_box_counts||{};const body=[...document.querySelectorAll('.v424-modal-layer .modal-body')].at(-1)||document.getElementById('modalBody');if(body)window.ModalContentRuntime.replace(body,reviewHtml412());toast(`已将 ${r.changed_boxes||0} 个 ${source} 标注改为 ${target}`)};
  window.importNoClean412=async()=>{const ids=[...state.import412Selected];await markReady412(ids);closeModal();state.data412Tab='processed';if(state.page==='数据集')renderDatasets424()};
  window.importClean412=()=>{const ids=[...state.import412Selected];if(!ids.length)return toast('请选择需要清洗的素材');closeModal();createClean427({image_ids:ids})};

  // ZIP review is owned by the explicit successful import-completion event.
  window.completeZipImportReview412=function(jobId){
    const t=state.import411;if(!t||String(t.jobId||'')!==String(jobId||'')||t.__reviewBound)return;
    t.__reviewBound=true;
    const extra=`<div class="row end"><button class="btn primary review412-btn" onclick="showImportReview412('${t.jobId}')">整理本次导入素材</button></div>`;
    if(!String(t.resultHtml||'').includes('review412-btn'))t.resultHtml=String(t.resultHtml||'')+extra;
    const syncReview=()=>{const r=document.getElementById('zip411Result');if(r&&!r.querySelector('.review412-btn'))r.insertAdjacentHTML('beforeend',extra);if(r&&!t.__autoReviewOpened){t.__autoReviewOpened=true;setTimeout(()=>showImportReview412(t.jobId),280)}};
    syncReview();setTimeout(syncReview,30);
  };

  // Plain image upload after success: ask for cleaning decision instead of leaving raw images indefinitely.
  const oldImageUpload412=window.doUploadImages426;
  window.doUploadImages426=function(inp){const before=new Set((state.images||[]).map(x=>String(x.id)));oldImageUpload412(inp);let tries=0;const timer=setInterval(async()=>{tries++;const out=document.getElementById('up411Result');if(out?.querySelector('.alert.ok')){clearInterval(timer);await window.loadCore412();const ids=(state.images||[]).filter(x=>!before.has(String(x.id))).map(x=>String(x.id));if(!window.__v414UploadDecision&&ids.length&&!out.querySelector('.review412-image'))out.insertAdjacentHTML('beforeend',`<div class="import412-decision review412-image"><div><b>本次图片是否需要清洗？</b><span>无需清洗后会直接进入“已处理 · 待标注”。</span></div><div class="row"><button class="btn" onclick='markReady412(${JSON.stringify(ids)});closeModal();setPage("数据集")'>无需清洗</button><button class="btn primary" onclick='closeModal();createClean427({image_ids:${JSON.stringify(ids)}})'>需要清洗</button></div></div>`)}if(tries>80)clearInterval(timer)},250)};

  // -------- selection controls for all material pickers --------
  window.trainSelectAll412=function(mode){const q=(document.getElementById('tr429Q')?.value||'').toLowerCase(),labs=[...(state.train429PickerLabels||new Set())],rows=(state.images||[]).filter(x=>isProcessed412(x)&&x.annotated&&(!q||String(x.filename).toLowerCase().includes(q))&&(!labs.length||labs.some(l=>(x.labels||[]).includes(l)))),selected=new Set(window.TrainingDraftRuntime?.materialIds?.()||[]);rows.forEach(x=>{const id=String(x.id);if(mode==='invert'){selected.has(id)?selected.delete(id):selected.add(id)}else selected.add(id)});window.TrainingDraftRuntime?.setMaterialIds?.([...selected]);renderTrainPicker429()};
  const baseOpenTrainPicker412=window.openTrainPicker429;
  window.openTrainPicker429=function(){baseOpenTrainPicker412();setTimeout(()=>{const q=document.getElementById('tr429Q');if(q&&!document.getElementById('tr412SelectBar'))q.insertAdjacentHTML('afterend','<div id="tr412SelectBar" class="picker412-actions"><button class="btn mini" onclick="trainSelectAll412(\'all\')">全选当前</button><button class="btn mini" onclick="trainSelectAll412(\'invert\')">反选当前</button></div>')},30)};
  window.aiRefSelect412=function(mode){const q=(document.getElementById('ai429RefQ')?.value||'').toLowerCase(),labs=[...(state.ai429RefLabels||new Set())],rows=(state.images||[]).filter(x=>x.annotated&&(!q||String(x.filename||'').toLowerCase().includes(q))&&(!labs.length||labs.some(l=>(x.labels||[]).includes(l))));rows.forEach(x=>mode==='invert'?(state.ai429RefSelected.has(x.id)?state.ai429RefSelected.delete(x.id):state.ai429RefSelected.add(x.id)):state.ai429RefSelected.add(x.id));renderAiRefs429()};
  const baseCreateAi412=window.createAiLabel429;
  window.createAiLabel429=function(opts={}){baseCreateAi412(opts);setTimeout(()=>{const q=document.getElementById('ai429RefQ');if(q&&!document.getElementById('ai412SelectBar'))q.insertAdjacentHTML('afterend','<div id="ai412SelectBar" class="picker412-actions"><button class="btn mini" onclick="aiRefSelect412(\'all\')">全选当前</button><button class="btn mini" onclick="aiRefSelect412(\'invert\')">反选当前</button></div>')},30)};window.createAiLabel427=window.createAiLabel429;

  // Cleaning review explicit all/invert.
  const baseCleanDetail412=window.cleanDetail429;
  window.cleanDetail429=async function(id){await baseCleanDetail412(id);setTimeout(()=>{const head=[...document.querySelectorAll('.clean429-card header')].find(x=>x.textContent.includes('逐图确认'));if(head&&!head.querySelector('.clean412-sel'))head.insertAdjacentHTML('beforeend','<div class="clean412-sel"><button class="btn mini" onclick="cleanSelect412(\'all\')">全选</button><button class="btn mini" onclick="cleanSelect412(\'invert\')">反选</button></div>')},20)};
  window.cleanSelect412=mode=>{const boxes=[...document.querySelectorAll('.review427-card input[type=checkbox]')];boxes.forEach(cb=>{const id=cb.getAttribute('onchange')?.match(/'([^']+)'/)?.[1];if(!id)return;const on=mode==='invert'?!cb.checked:true;cb.checked=on;on?state.v427CleanConfirm.add(String(id)):state.v427CleanConfirm.delete(String(id))})};

  // Data quality button: stable, visible user-oriented report; works inside stacked training modal.
  window.trainQuality429=async function(){const ids=window.TrainingDraftRuntime?.materialIds?.()||[];if(!ids.length)return toast('尚未选择素材');const btn=window.event?.currentTarget;if(btn){btn.disabled=true;btn.textContent='正在分析'}try{const r=await api(`/api/v44/projects/${pid()}/data-quality`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:ids})}),q=r.quality||{},scores=q.scores||{},labs=Object.entries(q.label_boxes||{}).sort((a,b)=>b[1]-a[1]);modal('本次训练素材质量',`<div class="quality412"><div class="report429-kpis"><div><span>图片</span><b>${q.images??ids.length}</b></div><div><span>已标注</span><b>${q.annotated_images??0}</b></div><div><span>有效标注框</span><b>${q.box_count??0}</b></div><div><span>综合质量</span><b>${q.overall_score??'-'}</b></div></div><section><b>质量维度</b><div class="quality412-grid">${Object.entries(scores).map(([k,v])=>`<div><span>${esc(k)}</span><b>${Number(v||0).toFixed(1)}</b><i><em style="width:${Math.max(0,Math.min(100,Number(v||0)))}%"></em></i></div>`).join('')}</div></section><section><b>标签数量</b><div class="data426-chips">${labs.map(([k,v])=>`<span class="data426-chip on">${esc(k)} · ${v}</span>`).join('')||'<span class="muted">暂无标签</span>'}</div></section><div class="row end"><button class="btn" onclick="closeModal()">关闭</button></div></div>`,true)}catch(e){toast(e.message||e)}finally{if(btn){btn.disabled=false;btn.textContent='查看数据质量'}}};

  // Final routing: do not fall back through older dataset/algorithm render layers.
  const oldRender412=render;
  render=function(){renderNav();renderTop();renderSummary();if(state.page==='算法列表'){renderAlgorithms423();return}if(state.page==='数据集'){renderDatasets424();return}oldRender412()};
  const top412=renderTop;renderTop=function(){top412();const v=document.getElementById('versionBadge');if(v)v.textContent='v'+V412;const r=document.getElementById('refreshBtn');if(r)r.onclick=async()=>{r.disabled=true;try{await window.loadCore412();if(!state.__extras412)state.__extras412=extras412().finally(()=>state.__extras412=null);render();toast('已刷新')}finally{r.disabled=false}}};
})();


/* v42.13 startup prepared snapshot */
(()=>{
 const V413='42.24.0', sleep=ms=>new Promise(r=>setTimeout(r,ms));
 window.__v53BootstrapOwned=true;
 function savedProject(){try{return JSON.parse(localStorage.getItem('mc_train_ui_state_v34')||'{}').projectId||''}catch(e){return ''}}
 function boot(st){const p=Math.max(0,Math.min(100,Number(st?.progress||0)));return `<div class="boot413"><div class="boot413-card"><div class="boot413-brand"><i></i><div><b>畅联云算法训练</b><span>正在准备平台数据</span></div></div><div class="boot413-progress"><div><span>${esc(st?.stage||'正在启动')}</span><b>${Math.round(p)}%</b></div><i><em style="width:${p}%"></em></i><p>${esc(st?.message||'正在读取历史素材、标注和算法版本')}</p></div><div class="boot413-note">start.bat 会先把核心数据与训练环境准备好，再进入平台。</div></div></div>`}
 async function waitReady(){const view=document.getElementById('view');let st={progress:0,stage:'连接平台服务',message:'正在确认启动状态'};if(view)view.innerHTML=boot(st);for(let i=0;i<1800;i++){let r=null;try{r=await api('/api/v53/bootstrap/status')}catch(e){}if(r){st=r;if(view)view.innerHTML=boot(st);if(r.status==='ready')return r;if(r.status==='failed')throw new Error(r.message||r.error||'平台数据预加载失败')}await sleep(i<30?300:650)}throw new Error('平台数据准备时间过长，请查看 start.bat 启动窗口。')}
 function apply(s){state.projects=s.projects||[];state.project=s.project||null;state.datasets=s.datasets||[];state.datasetId=state.datasets.find(d=>d.id===state.datasetId)?.id||state.datasets[0]?.id||'default';state.images=s.images||[];state.materialSummary61=s.material_summary;state.annotationSummary61=s.annotation_summary;state.labels=s.labels||[];state.algorithms=s.algorithms||[];state.jobs=s.jobs||[];state.models=s.models||[];state.targets=s.targets||[];state.inferenceEnvs=s.inference_envs||[];state.rec=s.recommendation||null;state.localModels=s.local_models||[];state.modelConfigs=s.model_configs||[];state.pending=s.pending||[];state.testModels=s.test_models||[];state.versionInfo={version:V413,name:'畅联云算法训练'};try{const x=JSON.parse(localStorage.getItem('mc_train_ui_state_v34')||'{}');x.projectId=state.project?.id||'';x.ts=Date.now();localStorage.setItem('mc_train_ui_state_v34',JSON.stringify(x))}catch(e){}}
 window.loadStartupSnapshot413=async function(force=false){const requested=savedProject();if(force)await api('/api/v53/bootstrap/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({preferred_project_id:requested,force:true})});if(requested&&!force){try{const direct=await api(`/api/v53/bootstrap/snapshot?preferred_project_id=${encodeURIComponent(requested)}`);apply(direct);return direct}catch(e){}}await waitReady();const s=await api(`/api/v53/bootstrap/snapshot?preferred_project_id=${encodeURIComponent(requested)}`);apply(s);return s};
 window.__clInit=function(){if(window.__v53InitPromise)return window.__v53InitPromise;const view=document.getElementById('view');window.__v53InitPromise=(async()=>{try{await window.loadStartupSnapshot413(false);await window.refreshCurrentPage413();state.uiReady=true;render()}catch(e){window.__v53InitPromise=null;if(view)view.innerHTML=`<div class="boot413"><div class="boot413-card error"><b>平台数据加载失败</b><p>${esc(e.message||e)}</p><div class="row"><button class="btn primary" onclick="window.__clInit()">重新加载</button><button class="btn" onclick="location.reload()">刷新页面</button></div></div></div>`}})();return window.__v53InitPromise};
 const oldTop=renderTop;renderTop=function(){oldTop();const v=document.getElementById('versionBadge');if(v)v.textContent='v'+V413;const r=document.getElementById('refreshBtn');if(r)r.onclick=async()=>{r.disabled=true;const t=r.textContent;r.textContent='刷新中';try{await window.refreshCurrentPage413();render();toast('当前页面已刷新')}catch(e){toast(e.message||e)}finally{r.disabled=false;r.textContent=t||'刷新'}}};
})();

/* ============================================================
 * v42.14 final stability layer
 * - central label schema (English code + Chinese display)
 * - reliable annotation save / live thumbnail overlay
 * - stable algorithm CRUD
 * - batch cleaning / skip-cleaning
 * - latest-version iteration visibility
 * - charted training data-quality report
 * ============================================================ */
(()=>{
  const V414='42.24.0';
  window.__v414UploadDecision=true;
  state.label414Usage=state.label414Usage||[];
  state.batch414Selected=state.batch414Selected||new Set();
  state.iteration414=state.iteration414||{};

  const labelByCode414=code=>(state.labels||[]).find(x=>String(x.code)===String(code));
  const labelText414=code=>{const l=labelByCode414(code);return l?(l.display_name&&l.display_name!==l.code?`${l.code} · ${l.display_name}`:l.code):code};
  const englishCode414=v=>/^[A-Za-z][A-Za-z0-9_-]*$/.test(String(v||'').trim());
  const safeNum414=v=>Math.max(0,Math.min(100,Number(v)||0));
  const isProcessed414=x=>!!(x?.annotated||x?.processing_status==='processed'||x?.cleaned_at||x?.clean_skipped);
  const unwrapAlgorithm414=r=>window.PlatformCore?.algorithms?.unwrapAlgorithmResponse(r)||(r?.algorithm||r);
  const iterationPresentation414=b=>window.PlatformCore?.training?.iterationBasePresentation(b)||(b==null?{title:'正在读取最新版本…',detail:'',status:'loading'}:b.error?{title:'读取失败',detail:String(b.error),status:'error'}:b.version_name?{title:`从最新可训练版本继续：${b.version_name}`,detail:b.model_name||'模型权重',status:'version'}:{title:'首次训练：使用所选母模型',detail:'后续版本会自动以上一个可用版本继续训练',status:'mother'});

  async function refreshLabels414(withUsage=false){
    const r=await api(withUsage?`/api/v54/projects/${pid()}/label-schema`:`/api/v12/projects/${pid()}/labels`);
    state.labels=(r.items||[]);
    if(withUsage)state.label414Usage=r.items||[];
    return state.labels;
  }
  async function refreshImages414(){
    const rows=await api(`/api/projects/${pid()}/images`);
    if(Array.isArray(rows))state.images=rows;
    return state.images||[];
  }
  window.refreshLabels414=refreshLabels414;

  // ---------- visible configuration center: label schema ----------
  const icon414={工作台:'▦',质量中心:'◇',算法列表:'◆',训练任务:'▶',数据集:'▤',视频切帧:'▣','自动标注及清洗':'✦',测试发布:'✓',检测台:'◎',标签管理:'Aa',部署转换:'⇄',部署产物:'▥',模型配置:'◉',训练资源:'▧',部署资源:'⬡'};
  renderNav=function(){
    const groups=[
      {title:'总览',items:['工作台','质量中心']},
      {title:'算法生产',items:['算法列表','训练任务']},
      {title:'数据中心',items:['数据集','视频切帧','自动标注及清洗']},
      {title:'测试评测',items:['测试发布','检测台']},
      {title:'配置中心',items:['标签管理']},
    ];
    if(state.v427Advanced)groups.push({title:'部署中心',items:['部署转换','部署产物']},{title:'资源配置',items:['模型配置','训练资源','部署资源']});
    document.getElementById('nav').innerHTML=`<div class="nav-project"><div class="nav-project-k">当前项目</div><div class="nav-project-v">${esc(state.project?.name||'默认空间')}</div></div>${groups.map(g=>`<div class="nav-group"><div class="nav-group-title">${g.title}</div>${g.items.map(n=>`<button class="nav-btn ${state.page===n?'active':''}" onclick="setPage('${n}')"><span class="nav-left"><i>${icon414[n]||'•'}</i><b>${n}</b></span><span class="nav-arrow">›</span></button>`).join('')}</div>`).join('')}<div class="nav-advanced427"><button onclick="toggleAdvanced427()">${state.v427Advanced?'收起高级功能':'展开高级功能'}</button></div><div class="nav-footer"><span>Version</span><b>v${V414}</b></div>`;
  };

  window.renderLabelManagement414=async function(){
    const view=document.getElementById('view');
    view.innerHTML=`<section class="label414-shell"><div class="label414-head"><div><h2>标签管理</h2><p>标签英文编码用于训练、导入导出和模型结果；中文名称用于业务展示。</p></div><button class="btn primary" onclick="openLabel414()">＋ 新建标签</button></div><section class="panel"><div class="label414-table" id="label414Table"><div class="empty">正在读取标签库…</div></div></section></section>`;
    try{await refreshLabels414(true);drawLabel414()}catch(e){document.getElementById('label414Table').innerHTML=`<div class="empty">读取失败：${esc(e.message||e)}</div>`}
  };
  function drawLabel414(){
    const box=document.getElementById('label414Table');if(!box)return;
    const rows=state.label414Usage||state.labels||[];
    box.innerHTML=`<div class="label414-row head"><span>英文标签</span><span>中文名称</span><span>颜色</span><span>快捷键</span><span>使用图片</span><span>标注框</span><span>操作</span></div>${rows.map(l=>`<div class="label414-row"><span><b class="label414-code">${esc(l.code)}</b></span><span>${esc(l.display_name||'-')}</span><span><i class="label414-color" style="background:${esc(l.color||'#64748b')}"></i>${esc(l.color||'')}</span><span>${esc(l.hotkey||'-')}</span><span>${Number(l.usage_images||0)}</span><span>${Number(l.usage_boxes||0)}</span><span class="row"><button class="btn mini" onclick="openLabel414(${Number(l.class_id)})">编辑</button><button class="btn mini danger" onclick="deleteLabel414(${Number(l.class_id)},'${esc(l.code)}')">删除</button></span></div>`).join('')||'<div class="empty">暂无标签。请先创建英文标签，例如 fire / smoke / person。</div>'}`;
  }
  window.openLabel414=function(classId=null){
    const l=classId===null?null:(state.labels||[]).find(x=>Number(x.class_id)===Number(classId));
    modal(l?'编辑标签':'新建标签',`<div class="label414-form"><div class="field"><label>英文标签 <em>*</em></label><input id="label414Code" class="input" value="${esc(l?.code||'')}" placeholder="例如 fire / smoke / helmet"><small>用于训练类别、模型输出、YOLO/COCO 导入导出；只允许英文、数字、_、-，且必须以英文字母开头。</small></div><div class="field"><label>中文名称</label><input id="label414Cn" class="input" value="${esc(l?.display_name||'')}" placeholder="例如 明火 / 烟雾 / 安全帽"></div><div class="form two"><div class="field"><label>显示颜色</label><input id="label414Color" class="input color414" type="color" value="${esc(l?.color||'#ef4444')}"></div><div class="field"><label>快捷键</label><input id="label414Hotkey" class="input" maxlength="1" value="${esc(l?.hotkey||'')}" placeholder="1-9"></div></div><div class="label414-preview"><span style="background:${esc(l?.color||'#ef4444')}"></span><b>${esc(l?.code||'fire')}</b><em>${esc(l?.display_name||'明火')}</em></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveLabel414(${classId===null?'null':Number(classId)})">保存</button></div>`,false);
  };
  window.saveLabel414=async function(classId){
    const code=(document.getElementById('label414Code')?.value||'').trim(),display=(document.getElementById('label414Cn')?.value||'').trim(),color=document.getElementById('label414Color')?.value||'',hotkey=(document.getElementById('label414Hotkey')?.value||'').trim();
    if(!englishCode414(code))return toast('英文标签格式不正确，例如 fire、smoke、yellow_helmet');
    if(hotkey&&!/^[1-9]$/.test(hotkey))return toast('快捷键只能填写 1-9');
    try{
      if(classId===null){await api(`/api/projects/${pid()}/labels`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:code,display_name:display||code,color})})}
      else await api(`/api/v12/projects/${pid()}/labels/${classId}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({code,display_name:display||code,color,hotkey})});
      await Promise.all([refreshLabels414(true),refreshImages414()]);closeModal();
      if(state.page==='标签管理')drawLabel414();
      toast(classId===null?'标签已创建':'标签及已有标注已同步更新');
    }catch(e){toast(e.message||e)}
  };
  window.deleteLabel414=async function(classId,code){
    if(!confirm(`确认删除标签 ${code}？已被标注框使用的标签不能删除。`))return;
    try{await api(`/api/v12/projects/${pid()}/labels/${classId}`,{method:'DELETE'});await refreshLabels414(true);drawLabel414();toast('标签已删除')}catch(e){toast(e.message||e)}
  };

  // ---------- annotation: schema only, no label management inside image ----------
  window.openAnnotation=async function(id){
    const img=(state.images||[]).find(x=>String(x.id)===String(id));if(!img)return toast('图片不存在或尚未加载');
    try{
      if(!Array.isArray(state.annotationQueue414)||!state.annotationQueue414.some(x=>String(x)===String(id)))state.annotationQueue414=[String(id)];
      if(!(state.labels||[]).length)await refreshLabels414(false);
      state.activeImage=img;state.activeBox=null;state.annZoom=1;state.annHistory=[];state.annRedo=[];
      const r=await api(`/api/projects/${pid()}/annotations/${id}`);state.ann=r?.annotation||{boxes:[]};if(!Array.isArray(state.ann.boxes))state.ann.boxes=[];
      const first=(state.labels||[]).find(l=>state.ann.boxes.some(b=>Number(b.class_id)===Number(l.class_id)))||(state.labels||[])[0];state.activeLabel=first?.class_id??null;state.annDirty=false;
      renderAnnotator();
    }catch(e){toast(`打开标注失败：${e.message||e}`)}
  };
  renderAnnotator=function(){
    const img=state.activeImage;if(!img)return;const idx=typeof imgIndex==='function'?imgIndex():-1,hasLabels=(state.labels||[]).length>0;
    modal('图片标注',`<div class="ann-layout pro ann414"><div class="ann-work"><div class="ann-toolbar"><button id="ann414Save" class="btn primary small" onclick="saveAnn(false)">保存标注</button><button class="btn small" onclick="prevImage()" ${idx<=0?'disabled':''}>上一张</button><button class="btn small" onclick="nextImage()" ${idx<0||idx>=state.images.length-1?'disabled':''}>下一张</button><button class="btn small" onclick="undoAnn()">撤销</button><button class="btn small" onclick="redoAnn()">重做</button><button class="btn small danger" onclick="deleteActiveBox()">删除框</button><span class="ann414-state">${esc(img.filename)} · <b id="annSaveState">已保存</b></span><div class="ann-zoom"><button class="btn mini" onclick="zoomAnn(-0.1)">-</button><span id="zoomText">100%</span><button class="btn mini" onclick="zoomAnn(0.1)">+</button></div></div>${hasLabels?'':`<div class="ann414-emptylabel"><b>标签库为空，暂时不能画框</b><span>请先到“配置中心 → 标签管理”创建英文标签。</span><button class="btn primary" onclick="closeModal();setPage('标签管理')">去标签管理</button></div>`}<div class="ann-canvas-wrap"><div id="annStage" class="ann-stage ${hasLabels?'':'disabled'}" style="transform:scale(${state.annZoom});transform-origin:top center"><img id="annImg" src="${img.url}"></div></div></div><aside class="side-panel ann-side"><div class="side-section"><div class="side-title">当前标签</div><div class="ann414-schema-note">标签来自配置中心，标注窗口只负责选择和使用。</div><div id="annLabels"></div></div><div class="side-section"><div class="side-title">标注框 <span>${state.ann.boxes.length}</span></div><div id="annBoxes"></div></div><div class="hint-card">拖拽空白处新建框；拖动框可移动；拖动四角可缩放；数字键切换标签；Ctrl+S 保存。</div></aside></div>`,true);
    const im=document.getElementById('annImg'),ready=()=>{drawBoxes();if(hasLabels)bindAnnotationEvents();renderAnnSide()};if(im?.complete)ready();else if(im)im.onload=ready;
  };
  renderAnnSide=function(){
    const labels=state.labels||[],a=document.getElementById('annLabels'),bb=document.getElementById('annBoxes');
    if(a)a.innerHTML=labels.map(l=>`<button class="ann414-label ${Number(state.activeLabel)===Number(l.class_id)?'active':''}" onclick="state.activeLabel=${Number(l.class_id)};renderAnnSide()"><i style="background:${esc(l.color||'#64748b')}"></i><span><b>${esc(l.code)}</b><em>${esc(l.display_name||l.code)}</em></span><kbd>${esc(l.hotkey||'')}</kbd></button>`).join('')||'<div class="muted">暂无可用标签</div>';
    const boxes=state.ann?.boxes||[];
    if(bb)bb.innerHTML=boxes.map((b,i)=>{const l=labels.find(x=>Number(x.class_id)===Number(b.class_id));return `<div class="ann414-boxrow ${Number(state.activeBox)===i?'active':''}" onclick="state.activeBox=${i};drawBoxes();renderAnnSide()"><span><i style="background:${esc(l?.color||'#64748b')}"></i><b>${i+1}. ${esc(l?.code||b.label||'unknown')}</b><em>${esc(l?.display_name||'')}</em></span><select class="select" onclick="event.stopPropagation()" onchange="relabelBox414(${i},this.value)">${labels.map(x=>`<option value="${Number(x.class_id)}" ${Number(x.class_id)===Number(b.class_id)?'selected':''}>${esc(x.code)}${x.display_name&&x.display_name!==x.code?' · '+esc(x.display_name):''}</option>`).join('')}</select></div>`}).join('')||'<div class="muted">暂无框。选择标签后，在图片上拖拽即可。</div>';
  };
  window.relabelBox414=function(i,classId){const b=state.ann?.boxes?.[i],l=(state.labels||[]).find(x=>Number(x.class_id)===Number(classId));if(!b||!l)return;try{pushHistory()}catch(_){};b.class_id=l.class_id;b.label=l.code;state.activeBox=i;markDirty();drawBoxes();renderAnnSide()};

  window.saveAnn=async function(silent=false){
    if(!state.activeImage||!state.ann)return false;const btn=document.getElementById('ann414Save'),ss=document.getElementById('annSaveState');
    if(btn){btn.disabled=true;btn.textContent='保存中…'}if(ss)ss.textContent='保存中';
    try{
      const r=await api(`/api/projects/${pid()}/annotations/${state.activeImage.id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({boxes:state.ann.boxes||[]})});
      state.ann=r?.annotation||state.ann;if(!Array.isArray(state.ann.boxes))state.ann.boxes=[];
      const applyResult=window.PlatformCore?.annotation?.applyAnnotationResult;
      if(applyResult&&r?.image?.id)state.images=applyResult(state.images||[],r,state.ann.boxes||[]);
      const idx=(state.images||[]).findIndex(x=>String(x.id)===String(state.activeImage.id));
      if(idx>=0){if(!applyResult){const fresh=r?.image||{};Object.assign(state.images[idx],fresh);state.images[idx].box_count=state.ann.boxes.length;state.images[idx].annotated=state.ann.boxes.length>0;state.images[idx].labels=[...new Set(state.ann.boxes.map(b=>b.label).filter(Boolean))];state.images[idx].annotation_preview=state.ann.boxes.slice(0,64).map(b=>({class_id:b.class_id,label:b.label,x1:b.x1,y1:b.y1,x2:b.x2,y2:b.y2}))}if(state.ann.boxes.length)state.images[idx].processing_status='processed';state.activeImage=state.images[idx]}
      state.annDirty=false;if(ss)ss.textContent=`已保存 · ${state.ann.boxes.length}框`;drawBoxes();renderAnnSide();
      try{if(typeof invalidateQuality411==='function')invalidateQuality411()}catch(_){}
      // Patch only the affected material card. Re-rendering the full gallery here
      // blocks the main thread for seconds on large libraries and remounts the modal.
      try{if(state.page==='数据集'&&typeof patchMaterialCard412==='function')patchMaterialCard412(state.activeImage)}catch(_){}
      // If annotation was opened from an image-preview modal, refresh that preview in place as well.
      try{const layers=[...document.querySelectorAll('.v424-modal-layer')],under=layers.length>1?layers[layers.length-2]:null,stage=under?.querySelector('.data412-previewstage');if(stage&&state.activeImage){stage.innerHTML=`<img src="${state.activeImage.url}">${(state.activeImage.annotation_preview||[]).map(b=>{const l=labelByCode414(b.label),w=Math.max(0,(b.x2-b.x1)/(state.activeImage.width||1)*100),h=Math.max(0,(b.y2-b.y1)/(state.activeImage.height||1)*100),x=(b.x1/(state.activeImage.width||1)*100),y=(b.y1/(state.activeImage.height||1)*100);return `<i class="ov412-box" style="left:${x}%;top:${y}%;width:${w}%;height:${h}%;border-color:${esc(l?.color||'#ef4444')}"><b style="background:${esc(l?.color||'#ef4444')}">${esc(b.label||'')}</b></i>`}).join('')}`}}catch(_){}
      if(!silent)toast(`标注已保存：${state.ann.boxes.length} 个框`);return true;
    }catch(e){state.annDirty=true;if(ss)ss.textContent='保存失败';toast(`保存失败：${e.message||e}`);return false}
    finally{if(btn){btn.disabled=false;btn.textContent='保存标注'}}
  };

  // ---------- dataset: labels strictly from label library ----------
  function filterLabelItems414(){return (state.labels||[]).filter(l=>l&&l.code&&l.status!=='disabled'&&l.status!=='inactive')}
  const baseData414=window.renderDatasets424;
  window.renderDatasets424=function(){
    baseData414();
    if(state.data412Tab==='processed'){
      const chips=document.querySelector('.data426-filtertop .data426-chips');
      if(chips){const labs=filterLabelItems414();chips.innerHTML=`<button class="data426-chip clear ${state.data412Labels.size?'':'on'}" onclick="clearLabels412()">全部</button>${labs.map(l=>`<button class="data426-chip ${state.data412Labels.has(l.code)?'on':''}" onclick="toggleLabel412('${esc(l.code)}')"><b>${esc(l.code)}</b>${l.display_name&&l.display_name!==l.code?`<small>${esc(l.display_name)}</small>`:''}</button>`).join('')}`}
    }
    if(state.data412Tab==='unprocessed'){
      const head=document.querySelector('.data426-head .row');
      if(head&&!head.querySelector('.batch414-clean'))head.insertAdjacentHTML('afterbegin',`<button class="btn batch414-clean" onclick="openBatch414('clean')">批量清洗</button><button class="btn batch414-ready" onclick="openBatch414('ready')">批量无需清洗</button>`);
      // Hide older broad actions to avoid duplicate semantics.
      [...document.querySelectorAll('.data426-head .row > button')].forEach(b=>{if(['清洗当前素材','当前素材无需清洗'].includes(b.textContent.trim()))b.style.display='none'});
    }
  };
  window.openBatch414=function(mode,ids=null){
    const candidates=ids?[...(state.recentUploadedMaterials61||[]),...(state.images||[])]:state.images||[],all=[...new Map(candidates.map(x=>[String(x.id),x])).values()].filter(x=>!x.annotation_index_pending&&!isProcessed414(x)&&!x.annotated),allowed=new Set((ids||all.map(x=>x.id)).map(String));const rows=all.filter(x=>allowed.has(String(x.id)));if(!rows.length)return toast('没有可操作的未处理素材');state.batch414Selected=new Set(rows.map(x=>String(x.id)));
    modal(mode==='clean'?'批量清洗':'批量无需清洗',`<div class="batch414"><div class="batch414-tools"><span>共 ${rows.length} 张未处理素材</span><div class="row"><button class="btn mini" onclick="selectBatch414('all')">全选</button><button class="btn mini" onclick="selectBatch414('invert')">反选</button></div></div><div id="batch414Grid" class="batch414-grid"></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="confirmBatch414('${mode}')">${mode==='clean'?'开始清洗':'确认无需清洗'}</button></div></div>`,true);renderBatch414(rows)
  };
  function renderBatch414(rows){const box=document.getElementById('batch414Grid');if(!box)return;box.innerHTML=rows.map(x=>`<label class="batch414-card ${state.batch414Selected.has(String(x.id))?'selected':''}"><input type="checkbox" ${state.batch414Selected.has(String(x.id))?'checked':''} onchange="toggleBatch414('${x.id}',this.checked)"><img src="${x.url}" loading="lazy"><span>${esc(x.filename)}</span></label>`).join('')}
  window.toggleBatch414=(id,on)=>{on?state.batch414Selected.add(String(id)):state.batch414Selected.delete(String(id));const cb=[...document.querySelectorAll('.batch414-card input')];cb.forEach(x=>x.closest('.batch414-card')?.classList.toggle('selected',x.checked))};
  window.selectBatch414=mode=>{[...document.querySelectorAll('.batch414-card input')].forEach(cb=>{cb.checked=mode==='invert'?!cb.checked:true;cb.dispatchEvent(new Event('change'))})};
  window.confirmBatch414=function(mode){const ids=[...state.batch414Selected];if(!ids.length)return toast('请选择素材');closeModal();if(mode==='clean')createClean427({image_ids:ids});else markReady412(ids)};

  // After plain image upload, replace old decision with batch-capable actions for this import.
  const upload414=window.doUploadImages426;
  window.doUploadImages426=function(inp){
    const before=new Set((state.images||[]).map(x=>String(x.id)));upload414(inp);let n=0;const t=setInterval(()=>{n++;const result=document.getElementById('up411Result');if(result?.querySelector('.alert.ok')){clearInterval(t);const ids=(state.images||[]).filter(x=>!before.has(String(x.id))).map(x=>String(x.id));result.querySelectorAll('.review412-image').forEach(x=>x.remove());if(ids.length&&!result.querySelector('.upload414-decision'))result.insertAdjacentHTML('beforeend',`<div class="upload414-decision"><div><b>本次上传 ${ids.length} 张素材</b><span>请选择是否需要清洗；确认后会进入对应处理流程。</span></div><div class="row"><button class="btn" onclick='closeModal();openBatch414("ready",${JSON.stringify(ids)})'>批量无需清洗</button><button class="btn primary" onclick='closeModal();openBatch414("clean",${JSON.stringify(ids)})'>批量清洗</button></div></div>`)}if(n>120)clearInterval(t)},250)
  };

  // ---------- stable algorithm CRUD ----------
  window.openNewAlgorithm423=function(){
    modal('新建算法',`<div class="alg414-form"><div class="field"><label>算法名称 <em>*</em></label><input id="alg414Name" class="input" placeholder="例如 烟火判断"></div><div class="form two"><div class="field"><label>行业场景</label><input id="alg414Industry" class="input" placeholder="例如 消防安全"></div><div class="field"><label>算法类型</label><select id="alg414Type" class="select"><option value="yolo_ultralytics">YOLO / Ultralytics</option><option value="paddle_detection">PaddleDetection</option><option value="opencv">OpenCV 传统视觉</option><option value="mmdetection">MMDetection</option><option value="custom_python">自定义 Python / 其他</option></select></div></div><div class="field"><label>备注</label><textarea id="alg414Remark" class="textarea" rows="4" placeholder="描述用途、目标或场景"></textarea></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button id="alg414Save" class="btn primary" onclick="saveNewAlgorithm414()">创建算法</button></div>`,false)
  };
  window.saveNewAlgorithm414=async function(){const name=(document.getElementById('alg414Name')?.value||'').trim(),industry=(document.getElementById('alg414Industry')?.value||'').trim(),algorithm_type=document.getElementById('alg414Type')?.value||'yolo_ultralytics',remark=(document.getElementById('alg414Remark')?.value||'').trim(),btn=document.getElementById('alg414Save');if(!name)return toast('请输入算法名称');if(btn){btn.disabled=true;btn.textContent='创建中…'}try{const r=await api(`/api/v12/projects/${pid()}/algorithms`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,industry,algorithm_type,remark})}),item=unwrapAlgorithm414(r);state.algorithms=[item,...(state.algorithms||[]).filter(x=>x.id!==item.id)];closeModal();renderAlgorithms423();toast('算法已创建')}catch(e){toast(`创建失败：${e.message||e}`)}finally{if(btn){btn.disabled=false;btn.textContent='创建算法'}}};
  window.editAlgorithm423=function(id){const a=(state.algorithms||[]).find(x=>String(x.id)===String(id));if(!a)return toast('算法不存在');modal('编辑算法',`<div class="alg414-form"><div class="field"><label>算法名称</label><input id="alg414EditName" class="input" value="${esc(a.name||'')}"></div><div class="form two"><div class="field"><label>行业场景</label><input id="alg414EditIndustry" class="input" value="${esc(a.industry||'')}"></div><div class="field"><label>算法类型</label><select id="alg414EditType" class="select">${[['yolo_ultralytics','YOLO / Ultralytics'],['paddle_detection','PaddleDetection'],['opencv','OpenCV 传统视觉'],['mmdetection','MMDetection'],['custom_python','自定义 Python / 其他']].map(([v,n])=>`<option value="${v}" ${a.algorithm_type===v?'selected':''}>${n}</option>`).join('')}</select></div></div><div class="field"><label>备注</label><textarea id="alg414EditRemark" class="textarea" rows="4">${esc(a.remark||'')}</textarea></div></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveEditAlgorithm414('${id}')">保存</button></div>`,false)};
  window.saveEditAlgorithm414=async id=>{const payload={name:(document.getElementById('alg414EditName')?.value||'').trim(),industry:(document.getElementById('alg414EditIndustry')?.value||'').trim(),algorithm_type:document.getElementById('alg414EditType')?.value||'',remark:(document.getElementById('alg414EditRemark')?.value||'').trim()};if(!payload.name)return toast('请输入算法名称');try{const r=await api(`/api/v12/projects/${pid()}/algorithms/${id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),item=unwrapAlgorithm414(r);const i=(state.algorithms||[]).findIndex(x=>String(x.id)===String(id));if(i>=0)state.algorithms[i]=item;closeModal();renderAlgorithms423();toast('算法已更新')}catch(e){toast(e.message||e)}};
  window.delAlgorithm=async id=>{const a=(state.algorithms||[]).find(x=>String(x.id)===String(id));if(!a)return;if(!confirm(`确认删除算法“${a.name}”？`))return;try{await api(`/api/v12/projects/${pid()}/algorithms/${id}`,{method:'DELETE'});state.algorithms=(state.algorithms||[]).filter(x=>String(x.id)!==String(id));renderAlgorithms423();toast('算法已删除')}catch(e){toast(e.message||e)}};

  // ---------- training iteration: make actual previous-version base visible ----------
  const startAlg414=window.startAlgorithmTraining429;
  window.startAlgorithmTraining429=async function(aid){
    startAlg414(aid);state.iteration414[aid]=null;
    try{const r=await api(`/api/v54/projects/${pid()}/algorithms/${aid}/iteration-base?framework=ultralytics`);state.iteration414[aid]=r.base||{};setTimeout(()=>showIterationBase414(aid),20)}catch(e){state.iteration414[aid]={error:String(e.message||e)};setTimeout(()=>showIterationBase414(aid),20)}
  };
  window.showIterationBase414=function(aid){const dynamic=[...document.querySelectorAll('.v424-modal-layer')].at(-1),layer=dynamic||document.querySelector('#modal:not(.hidden)'),body=layer?.querySelector('.modal-body');if(!body)return;let box=body.querySelector('.iteration414');if(!box){box=document.createElement('div');box.className='iteration414';body.prepend(box)}const p=iterationPresentation414(state.iteration414[aid]);box.innerHTML=`<span>迭代起点</span><b>${esc(p.title)}</b>${p.detail?`<em>${esc(p.detail)}</em>`:''}`};

  // ---------- charted data quality ----------
  function radar414(scores){const entries=Object.entries(scores||{}).slice(0,8);if(!entries.length)return '<div class="empty">暂无质量维度</div>';const n=entries.length,c=150,r=104,pts=entries.map(([k,v],i)=>{const a=-Math.PI/2+i*Math.PI*2/n,rr=r*safeNum414(v)/100;return [c+Math.cos(a)*rr,c+Math.sin(a)*rr]}),ring=[25,50,75,100].map(p=>{const q=entries.map((_,i)=>{const a=-Math.PI/2+i*Math.PI*2/n,rr=r*p/100;return `${c+Math.cos(a)*rr},${c+Math.sin(a)*rr}`}).join(' ');return `<polygon points="${q}" fill="none" stroke="currentColor" opacity="${p===100?.2:.09}"/>`}).join(''),axes=entries.map((_,i)=>{const a=-Math.PI/2+i*Math.PI*2/n;return `<line x1="${c}" y1="${c}" x2="${c+Math.cos(a)*r}" y2="${c+Math.sin(a)*r}" stroke="currentColor" opacity=".12"/>`}).join(''),poly=pts.map(p=>p.join(',')).join(' '),labels=entries.map(([k,v],i)=>{const a=-Math.PI/2+i*Math.PI*2/n,x=c+Math.cos(a)*(r+27),y=c+Math.sin(a)*(r+27),anchor=Math.abs(Math.cos(a))<.2?'middle':Math.cos(a)>0?'start':'end';return `<text x="${x}" y="${y}" text-anchor="${anchor}" dominant-baseline="middle"><tspan>${esc(k)}</tspan><tspan x="${x}" dy="15" class="score">${safeNum414(v).toFixed(0)}</tspan></text>`}).join('');return `<svg class="quality414-radar" viewBox="0 0 300 300">${ring}${axes}<polygon points="${poly}" class="quality414-poly"/>${pts.map(p=>`<circle cx="${p[0]}" cy="${p[1]}" r="4" class="quality414-dot"/>`).join('')}${labels}</svg>`}
  window.trainQuality429=async function(){const ids=window.TrainingDraftRuntime?.materialIds?.()||[];if(!ids.length)return toast('尚未选择训练素材');const btn=window.event?.currentTarget;if(btn){btn.disabled=true;btn.textContent='正在分析…'}try{const r=await api(`/api/v44/projects/${pid()}/data-quality`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:ids})}),q=r.quality||{},scores=q.scores||{},labs=Object.entries(q.label_boxes||{}).sort((a,b)=>b[1]-a[1]),max=Math.max(1,...labs.map(x=>Number(x[1])||0));modal('训练素材 · 数据质量',`<div class="quality414"><div class="quality414-hero"><div><span>综合质量</span><b>${Number(q.overall_score||0).toFixed(1)}</b><em>/ 100</em></div><p>${Number(q.overall_score||0)>=90?'数据状态很好，可直接进入训练。':Number(q.overall_score||0)>=75?'整体可训练，建议关注较弱维度。':'建议先处理弱项后再训练，避免低质量数据影响模型。'}</p></div><div class="quality414-main"><section>${radar414(scores)}</section><section class="quality414-kpis"><div><span>图片</span><b>${q.images??ids.length}</b></div><div><span>已标注</span><b>${q.annotated_images??0}</b></div><div><span>标注框</span><b>${q.box_count??0}</b></div><div><span>标签数</span><b>${q.label_count??labs.length}</b></div><div><span>无效框</span><b>${q.invalid_boxes??0}</b></div><div><span>低分辨率</span><b>${q.low_resolution??0}</b></div></section></div><section class="quality414-section"><h3>质量维度</h3><div class="quality414-bars">${Object.entries(scores).map(([k,v])=>`<div><span>${esc(k)}</span><i><em style="width:${safeNum414(v)}%"></em></i><b>${safeNum414(v).toFixed(1)}</b></div>`).join('')}</div></section><section class="quality414-section"><h3>标签分布</h3><div class="quality414-labelbars">${labs.map(([k,v])=>`<div><span><b>${esc(labelText414(k))}</b><em>${v} 框</em></span><i><em style="width:${Math.max(4,Number(v)/max*100)}%"></em></i></div>`).join('')||'<div class="empty">暂无标签统计</div>'}</div></section><div class="row end"><button class="btn" onclick="closeModal()">关闭</button></div></div>`,true)}catch(e){toast(e.message||e)}finally{if(btn){btn.disabled=false;btn.textContent='查看数据质量'}}};

  // ---------- final routing ----------
  const render414Base=render;
  render=function(){
    if(state.page==='标签管理'){renderNav();renderTop();renderSummary();renderLabelManagement414();return}
    render414Base();
    const vb=document.getElementById('versionBadge');if(vb)vb.textContent='v'+V414;
  };
})();
/* v42.14 compatibility: legacy model-config row may still call this name. */
window.editModelConfigV35 = window.editModelConfigV35 || ((id)=>window.openModelConfigModalV35(id));

/* v42.14 import label normalization: map imported labels to the central label library. */
(()=>{
  function importRows414(){const ids=(state.import412?.image_ids||[]).map(String),set=new Set(ids);return (state.images||[]).filter(x=>set.has(String(x.id)))}
  function importReview414Html(){
    const r=state.import412||{},rows=importRows414(),counts=r.label_box_counts||{},sources=Object.entries(counts),library=(state.labels||[]).filter(x=>x?.code);
    return `<div class="import412"><section class="import412-head"><div><span>本次导入整理</span><h2>${esc(r.file_name||'导入素材')}</h2><p>${rows.length} 张图片 · ${rows.filter(x=>x.annotated).length} 张带标注</p></div><div class="row"><button class="btn" onclick="selectImportAll414()">全选</button><button class="btn" onclick="invertImport414()">反选</button></div></section>${sources.length?`<section class="import412-labels"><header><b>标签归一化</b><span>把 ZIP 中的 class_0 等原始标签映射到“配置中心 → 标签管理”的标准英文标签。</span></header>${sources.map(([src,n])=>`<div class="import412-labelrow"><div><b>${esc(src)}</b><span>${n} 个框</span></div><span>→</span><select id="map414_${encodeURIComponent(src)}" class="select"><option value="">选择标准标签</option>${library.map(l=>`<option value="${esc(l.code)}" ${l.code===src?'selected':''}>${esc(l.code)}${l.display_name&&l.display_name!==l.code?' · '+esc(l.display_name):''}</option>`).join('')}</select><button class="btn primary" onclick="remapImport414(decodeURIComponent('${encodeURIComponent(src)}'),'map414_${encodeURIComponent(src)}')">应用</button></div>`).join('')}<div class="row end"><button class="btn mini" onclick="closeModal();setPage('标签管理')">管理标准标签</button></div></section>`:''}<section class="import412-grid">${rows.slice(0,180).map(x=>`<label class="import412-card ${state.import412Selected?.has(String(x.id))?'on':''}"><input type="checkbox" ${state.import412Selected?.has(String(x.id))?'checked':''} onchange="toggleImport414('${x.id}',this.checked)"><img src="${x.url}" loading="lazy"><b>${esc(x.filename)}</b><span>${x.annotated?esc((x.labels||[]).join('、')||'已标注'):'待标注'}</span></label>`).join('')}</section><section class="import412-decision"><div><b>本批素材是否需要清洗？</b><span>可以全选/反选后批量决定；清洗确认删除时图片与对应标注一起处理。</span></div><div class="row"><button class="btn" onclick="importNoClean414()">批量无需清洗</button><button class="btn primary" onclick="importClean414()">批量清洗</button></div></section></div>`;
  }
  window.showImportReview412=async function(jobId){await window.loadCore412();await refreshLabels414(false);const rr=await api(`/api/v52/projects/${pid()}/import/jobs/${jobId}/review`);state.import412={job_id:jobId,file_name:rr.job?.file_name||'',image_ids:rr.image_ids||[],label_box_counts:rr.label_box_counts||{}};state.import412Selected=new Set((rr.image_ids||[]).map(String));modal('本次导入素材',importReview414Html(),true)};
  window.toggleImport414=(id,on)=>{on?state.import412Selected.add(String(id)):state.import412Selected.delete(String(id));const body=[...document.querySelectorAll('.v424-modal-layer .modal-body')].at(-1);if(body)window.ModalContentRuntime.replace(body,importReview414Html())};
  window.selectImportAll414=()=>{(state.import412?.image_ids||[]).forEach(id=>state.import412Selected.add(String(id)));const body=[...document.querySelectorAll('.v424-modal-layer .modal-body')].at(-1);if(body)window.ModalContentRuntime.replace(body,importReview414Html())};
  window.invertImport414=()=>{(state.import412?.image_ids||[]).forEach(id=>state.import412Selected.has(String(id))?state.import412Selected.delete(String(id)):state.import412Selected.add(String(id)));const body=[...document.querySelectorAll('.v424-modal-layer .modal-body')].at(-1);if(body)window.ModalContentRuntime.replace(body,importReview414Html())};
  window.remapImport414=async function(source,selectId){const target=document.getElementById(selectId)?.value||'';if(!target)return toast('请选择标签库中的标准标签');const ids=[...state.import412Selected];if(!ids.length)return toast('请选择本次导入素材');try{const rr=await api(`/api/v52/projects/${pid()}/labels/remap`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:ids,source_label:source,target_label:target})});await Promise.all([window.loadCore412(),refreshLabels414(false)]);const review=await api(`/api/v52/projects/${pid()}/import/jobs/${state.import412.job_id}/review`);state.import412.label_box_counts=review.label_box_counts||{};const body=[...document.querySelectorAll('.v424-modal-layer .modal-body')].at(-1);if(body)window.ModalContentRuntime.replace(body,importReview414Html());toast(`已同步 ${rr.changed_boxes||0} 个框：${source} → ${target}`)}catch(e){toast(e.message||e)}};
  window.importNoClean414=async()=>{const ids=[...state.import412Selected];if(!ids.length)return toast('请选择素材');await markReady412(ids);closeModal();state.data412Tab='processed';if(state.page==='数据集')renderDatasets424()};
  window.importClean414=()=>{const ids=[...state.import412Selected];if(!ids.length)return toast('请选择素材');closeModal();createClean427({image_ids:ids})};
})();

/* M4 final activation: later compatibility layers must not replace these contracts. */
(()=>{
  if(window.__m4OpenModelConfig)window.openModelConfigModalV35=window.__m4OpenModelConfig;
  if(window.__m4TestModelConfig)window.testModelConfigV35=window.__m4TestModelConfig;
  if(window.__m4ReviewCandidates)window.reviewAiLabel427=window.__m4ReviewCandidates;
  if(window.__m4CreateDeployJob)window.createDeployJob=window.__m4CreateDeployJob;
  const baseSelect=window.selectDeployTarget;
  window.selectDeployTarget=function(kind){baseSelect(kind);setTimeout(()=>{if(kind==='rockchip'){const select=document.getElementById('dpChip');if(select)select.innerHTML='<option value="rk3588">RK3588</option><option value="rk3568">RK3568</option>'}if(kind==='tensorrt'&&!document.getElementById('dpTargetEnvironment')){const grid=document.querySelector('.deploy-config-panel .deploy-config-grid');if(grid)grid.insertAdjacentHTML('beforeend','<div class="field full"><label>目标环境</label><input id="dpTargetEnvironment" class="input" placeholder="例如 RTX 4090 · CUDA 12.8 · TensorRT 10.9"><small>TensorRT Engine 与 GPU/CUDA/TensorRT 环境绑定，必须明确记录。</small></div>')}},0)};
})();

/* v42.15 training contract: one candidate pool, configurable per-run random
 * experiment holdout, and a complete collapsed advanced-parameter panel. */
(()=>{
  const baseStartTraining415=window.startAlgorithmTraining429;
  const baseRefreshTraining415=window.refreshTrain429;
  const baseOpenSettings415=window.openTrainSettings429||window.openTrainSettings428;
  const baseSaveSettings415=window.saveTrainSettings428;
  const num415=(id,fallback)=>{const el=document.getElementById(id);const value=Number(el?.value);return Number.isFinite(value)?value:fallback};
  const ready415=x=>!!(x?.annotated||x?.processing_status==='processed'||x?.cleaned_at||x?.clean_skipped);
  const pool415=()=> (state.images||[]).filter(x=>ready415(x)&&x.annotated&&['train','val','unassigned'].includes(String(x.split||'unassigned').toLowerCase()));
  const cfg415=()=>window.trainingConfigCanonical428();
  function currentTrainingDialog415(){return document.querySelector('.train429-create')}
  function installExperimentControl415(){
    const root=currentTrainingDialog415(),summary=root?.querySelector('.train429-data-summary');
    if(!root||!summary||root.querySelector('#tr429ExperimentPercent'))return;
    const value=Number(state.train429ExperimentPercent||20);
    const rows=pool415(),train=rows.filter(x=>String(x.split||'unassigned').toLowerCase()==='train').length,exp=rows.filter(x=>String(x.split||'unassigned').toLowerCase()==='val').length,unassigned=rows.length-train-exp;
    summary.insertAdjacentHTML('beforeend',`<div class="train429-split-summary"><span>训练/试验候选</span><b>${train} / ${exp}${unassigned?` · 未分配 ${unassigned}`:''}</b></div><div class="train429-experiment-field field"><label>每次随机抽取试验集比例</label><div class="input-suffix428"><input id="tr429ExperimentPercent" class="input" type="number" min="1" max="99" step="1" value="${value}"><span>%</span></div><small>本次运行会从已选训练/试验候选中重新随机抽取；默认 20%，每次运行重新抽取。</small></div>`);
    const input=root.querySelector('#tr429ExperimentPercent');
    input?.addEventListener('input',()=>{const v=Math.max(1,Math.min(99,Number(input.value)||20));state.train429ExperimentPercent=v;const note=root.querySelector('.train429-split-summary b');if(note)note.textContent=`${train} / ${exp}${unassigned?` · 未分配 ${unassigned}`:''}`});
  }
  window.startAlgorithmTraining429=async function(aid){
    state.train429ExperimentPercent=Number(state.train429ExperimentPercent||20);
    const result=baseStartTraining415?.(aid);
    [30,160,500].forEach(delay=>setTimeout(installExperimentControl415,delay));
    return result;
  };
  window.refreshTrain429=function(){baseRefreshTraining415?.();installExperimentControl415()};

  function installAdvanced415(){
    const root=document.querySelector('.train428-settings'),details=root?.querySelector('details.advanced427-box');
    if(!root||!details||root.querySelector('#ts415Advanced'))return;
    const c=cfg415();
    details.querySelector('.form')?.insertAdjacentHTML('beforeend',`<div id="ts415Advanced" class="form four"><div class="field"><label>最终学习率 lrf</label><input id="ts428Lrf" class="input" type="number" min="0" max="1" step="0.0001" value="${c.lrf}"></div><div class="field"><label>Warmup epochs</label><input id="ts428Warmup" class="input" type="number" min="0" step="0.1" value="${c.warmup_epochs}"></div><div class="field"><label>关闭 Mosaic 轮次</label><input id="ts428CloseMosaic" class="input" type="number" min="0" value="${c.close_mosaic}"></div><div class="field"><label>Multi-scale</label><input id="ts428MultiScale" class="input" type="number" min="0" max="1" step="0.1" value="${c.multi_scale||0}"></div><div class="field"><label>HSV-H</label><input id="ts428HsvH" class="input" type="number" min="0" max="1" step="0.001" value="${c.hsv_h}"></div><div class="field"><label>HSV-S</label><input id="ts428HsvS" class="input" type="number" min="0" max="1" step="0.01" value="${c.hsv_s}"></div><div class="field"><label>HSV-V</label><input id="ts428HsvV" class="input" type="number" min="0" max="1" step="0.01" value="${c.hsv_v}"></div><div class="field"><label>旋转 degrees</label><input id="ts428Degrees" class="input" type="number" min="0" step="0.1" value="${c.degrees}"></div><div class="field"><label>平移 translate</label><input id="ts428Translate" class="input" type="number" min="0" max="1" step="0.01" value="${c.translate}"></div><div class="field"><label>缩放 scale</label><input id="ts428Scale" class="input" type="number" min="0" max="1" step="0.01" value="${c.scale}"></div><div class="field"><label>剪切 shear</label><input id="ts428Shear" class="input" type="number" min="0" step="0.1" value="${c.shear}"></div><div class="field"><label>透视 perspective</label><input id="ts428Perspective" class="input" type="number" min="0" max="1" step="0.01" value="${c.perspective}"></div><div class="field"><label>上下翻转 flipud</label><input id="ts428Flipud" class="input" type="number" min="0" max="1" step="0.01" value="${c.flipud}"></div><div class="field"><label>左右翻转 fliplr</label><input id="ts428Fliplr" class="input" type="number" min="0" max="1" step="0.01" value="${c.fliplr}"></div><div class="field"><label>单类别 single_cls</label><label class="check"><input id="ts428SingleCls" type="checkbox" ${c.single_cls?'checked':''}> 单类别训练</label></div><div class="field"><label>矩形训练 rect</label><label class="check"><input id="ts415Rect" type="checkbox" ${c.rect?'checked':''}> 启用 rect</label></div></div>`);
  }
  window.openTrainSettings429=function(){const result=baseOpenSettings415?.();setTimeout(installAdvanced415,20);return result};
  window.openTrainSettings428=window.openTrainSettings429;
  window.saveTrainSettings428=function(){
    const c=cfg415();Object.assign(c,{lrf:num415('ts428Lrf',c.lrf),warmup_epochs:num415('ts428Warmup',c.warmup_epochs),close_mosaic:num415('ts428CloseMosaic',c.close_mosaic),multi_scale:num415('ts428MultiScale',c.multi_scale),hsv_h:num415('ts428HsvH',c.hsv_h),hsv_s:num415('ts428HsvS',c.hsv_s),hsv_v:num415('ts428HsvV',c.hsv_v),degrees:num415('ts428Degrees',c.degrees),translate:num415('ts428Translate',c.translate),scale:num415('ts428Scale',c.scale),shear:num415('ts428Shear',c.shear),perspective:num415('ts428Perspective',c.perspective),flipud:num415('ts428Flipud',c.flipud),fliplr:num415('ts428Fliplr',c.fliplr),single_cls:!!document.getElementById('ts428SingleCls')?.checked,rect:!!(document.getElementById('ts415Rect')||document.getElementById('ts428Rect'))?.checked});window.TrainingDraftRuntime?.update?.({config:c});return baseSaveSettings415?.()};

  window.renderTrainPicker429=function(){
    const q=(document.getElementById('tr429Q')?.value||'').toLowerCase(),labs=[...(state.train429PickerLabels||new Set())],rows=pool415().filter(x=>(!q||String(x.filename||'').toLowerCase().includes(q))&&(!labs.length||labs.some(l=>(x.labels||[]).includes(l))));
    const g=document.getElementById('tr429Grid');if(!g)return;
    const label=x=>String(x.split||'unassigned').toLowerCase()==='val'?'试验候选':String(x.split||'unassigned').toLowerCase()==='train'?'训练候选':'未分配候选';
    g.innerHTML=rows.slice(0,300).map(x=>`<button class="${(window.TrainingDraftRuntime?.materialIds?.()||[]).includes(String(x.id))?'on':''}" onclick="toggleTrainImage429('${x.id}')"><img src="${x.url}" loading="lazy"><b>${esc(x.filename)}</b><span>${label(x)} · ${esc((x.labels||[]).join('、'))}</span></button>`).join('')||'<div class="empty">没有符合筛选条件的已处理标注图片</div>';
  };

  })();

/* v42.16 conversion resource readiness and non-blocking version conversion. */
(()=>{
  const resourceCacheKey416=()=>`cl_train_v428_deployresources_${pid()}_`;
  const historyCacheKey416=(aid,vid)=>`cl_train_v428_verdeploy_${pid()}_${aid}_${vid}`;
  const read416=k=>{try{return JSON.parse(localStorage.getItem(k)||'null')}catch(e){return null}};
  const write416=(k,v)=>{try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}};
  const targetKind416=t=>t==='rockchip'?'rockchip':t==='sophon'?'sophon':t==='ascend'?'ascend':'';
  const targetLabel416=t=>({ascend:'华为 Atlas / Ascend',rockchip:'瑞芯微 RKNN',sophon:'算能 Sophon'})[t]||t;
  const statusLabel416=s=>({ready:'可用',missing:'不可用',unchecked:'未检测',configured:'待检测'}[s]||s||'未知');
  const matching416=(rows,t)=> (rows||[]).filter(x=>String(x.kind||'').toLowerCase()===targetKind416(t)||(x.targets||[]).includes(t));
  async function resources416(){
    // Resource detection can change while the user is moving between the
    // deployment center and a version dialog. Always ask the local API for
    // the current readiness state; use the previous response only if the API
    // is temporarily unavailable so a transient error never hides resources.
    try{
      const r=await api('/api/v39/deploy/resources');write416(resourceCacheKey416(),r);return r;
    }catch(error){
      const cached=read416(resourceCacheKey416());
      if(cached?.items)return cached;
      throw error;
    }
  }
  async function history416(aid,vid){
    const k=historyCacheKey416(aid,vid),cached=read416(k);
    if(cached)return cached;
    const r=await api(`/api/v42/projects/${pid()}/algorithms/${aid}/versions/${vid}/deployments`);write416(k,r);return r;
  }
  function resourceStatusHtml416(rows,target){
    if(!rows.length)return `<div class="convert428-resource-status-empty"><b>尚未配置 ${esc(targetLabel416(target))} 转换资源</b><span>请到“高级功能 → 部署资源”新增本机工具链或远程转换服务器，再执行检测。</span></div>`;
    return rows.map(r=>{
      const ready=r.status==='ready'&&(r.targets||[]).includes(target);
      const detail=r.message||(!ready?'请执行资源检测并确认目标能力':'可以创建真实转换任务');
      return `<div class="convert428-resource-status-row ${ready?'ready':'not-ready'}"><div><b>${esc(r.name||r.id||'未命名资源')}</b><span>${esc(r.mode==='remote'?'远程服务器':'本机')} · ${esc(statusLabel416(r.status))}</span></div><p>${esc(detail)}</p></div>`;
    }).join('');
  }
  window.refreshConvertResource428=function(){
    const target=document.querySelector('input[name="conv428Target"]:checked')?.value||'ascend';
    const all=state.conv428Resources||[],configured=matching416(all,target),ready=configured.filter(x=>x.status==='ready'&&(x.targets||[]).includes(target));
    const sel=document.getElementById('conv428Resource'),chip=document.getElementById('conv428Chip'),warn=document.getElementById('conv428Warn'),status=document.getElementById('conv428ResourceStatus');
    if(sel){sel.innerHTML=ready.map(x=>`<option value="${esc(x.id)}">${esc(x.name||x.id)} · ${esc(x.mode==='remote'?'远程':'本机')}</option>`).join('')||'<option value="">暂无已检测可用资源</option>';sel.onchange=()=>{const r=all.find(x=>x.id===sel.value);if(target==='ascend'&&chip){const socs=r?.detected_soc_versions||r?.remote_health?.soc_versions||[];chip.value=socs[0]||''}}}
    const first=ready[0];
    if(chip){if(target==='rockchip')chip.value='rk3588';else if(target==='sophon')chip.value='bm1684x';else{const socs=first?.detected_soc_versions||first?.remote_health?.soc_versions||[];chip.value=socs[0]||''}}
    if(status)status.innerHTML=resourceStatusHtml416(configured,target);
    if(warn){
      if(ready.length)warn.textContent=target==='rockchip'?'已检测到可用 RKNN-Toolkit2；请选择 RK3588 或 RK3568 后创建真实转换任务。':target==='sophon'?'已检测到可用 TPU-MLIR；可生成真实 BMODEL。':'已检测到可用 Atlas/CANN 资源；请确认目标 soc_version。';
      else warn.textContent=target==='rockchip'?'Windows 本机通常无法安装官方 RKNN-Toolkit2；请配置 WSL2/Linux 或远程转换节点，检测通过后才能创建 .rknn。':`当前没有已检测通过的${targetLabel416(target)}资源；已配置资源的状态和处理建议见下方。`;
    }
  };
  window.openNewConvert428=async function(aid,vid){
    try{
      // Resource discovery and version history are independent; load both at once so the dialog never feels blocked.
      const [rr,hist]=await Promise.all([resources416(),history416(aid,vid)]),v=hist.version||{};
      if(!String(v.stored_path||'').trim())return toast('当前版本没有可用模型产物');
      modal('新建版本转换',`<div class="convert428-create"><section><b>源版本</b><div class="convert428-source"><span>${esc(hist.algorithm?.name||'-')}</span><strong>${esc(v.version_name||'-')}</strong><em>${esc(v.model_name||'')}</em></div></section><section><b>转换目标</b><div class="convert428-targets">${['ascend','rockchip','sophon'].map((t,i)=>`<label><input type="radio" name="conv428Target" value="${t}" ${i===0?'checked':''} onchange="refreshConvertResource428()"><i></i><b>${esc(targetLabel416(t))}</b><span>${t==='ascend'?'输出 .om':t==='rockchip'?'输出 .rknn':'输出 .bmodel'}</span></label>`).join('')}</div></section><section><div class="form two"><div class="field"><label>转换资源</label><select id="conv428Resource" class="select"></select></div><div class="field"><label>精度</label><select id="conv428Precision" class="select"><option value="fp16">FP16</option><option value="fp32">FP32</option><option value="int8">INT8（需要校准数据）</option></select></div><div class="field"><label>输入尺寸</label><input id="conv428Input" class="input" value="640"></div><div class="field"><label>芯片型号</label><input id="conv428Chip" class="input" value=""></div></div></section><div id="conv428Warn" class="alert soft"></div><section><b>已配置资源状态</b><div id="conv428ResourceStatus" class="convert428-resource-status"></div></section><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="submitConvert428('${aid}','${vid}')">开始转换</button></div></div>`,true);
      state.conv428Resources=rr.items||[];setTimeout(refreshConvertResource428,20);
    }catch(e){toast(e.message||e)}
  };
})();

window.installUsability417?.();

/* Durable v3 exact-material training split UI. The worker only sees user-selected image ids. */
(()=>{
  const previousStart=window.startAlgorithmTraining429;
  const trainingApi=()=>window.PlatformCore?.training;
  const num=(id,fallback)=>{const value=Number(document.getElementById(id)?.value);return Number.isFinite(value)?value:fallback};
  const splitState=()=>{
    const draft=state.trainingDraft||{};
    return {mode:draft.splitMode||'random_test_from_training_pool',train:new Set(draft.materialIds||[]),test:new Set(draft.testMaterialIds||[]),experiment:draft.experimentPercent??20,validation:draft.validationPercent??20};
  };
  const allCandidates=()=>trainingApi()?.filterTrainingMaterials(state.images||[])||[];
  const imageId=row=>String(row?.id||'');
  const labelText=code=>(state.labels||[]).find(row=>String(row.code)===String(code))?.display_name||code;
  const otherRole=role=>role==='train'?'test':'train';
  function eligibleFor(role){const s=splitState(),blocked=s.mode==='independent_test_set'?s[otherRole(role)]:new Set();return allCandidates().filter(row=>!blocked.has(imageId(row)))}
  function selectedLabels(ids){const chosen=new Set(ids),labels=new Set();(state.images||[]).forEach(row=>{if(chosen.has(imageId(row)))(row.labels||[]).forEach(code=>labels.add(labelText(code)))});return[...labels]}
  function renderResources(root,panel){
    if(root.querySelector('#trV3Device'))return;
    const resource=state.trainingDraft?.resource||{},report=state.trainingDevicesV3||{},options=report.options||[],field=document.createElement('section');
    field.className='train-v3-resources';
    field.innerHTML=`<header><b>执行设备与资源</b></header><div class="form two"><label class="field"><span>训练设备</span><select id="trV3Device" class="select">${options.map(row=>`<option value="${esc(row.id)}" ${row.available===false?'disabled':''}>${esc(row.label||row.id)}${row.available===false?'（不可用）':''}</option>`).join('')||'<option value="" disabled>设备读取失败</option>'}</select></label><label class="field"><span>GPU 使用策略</span><select id="trV3GpuPolicy" class="select"><option value="auto">自动</option><option value="exclusive">独占</option><option value="shared">共享</option></select></label></div><small>${esc(report.error||report.auto?.meaning||'按所选训练环境的可用设备执行')}</small>`;
    panel.before(field);field.querySelector('#trV3Device').value=resource.device||report.recommended||'auto';field.querySelector('#trV3GpuPolicy').value=resource.gpuPolicy||'auto';
  }
  function renderSplit(){
    const root=document.querySelector('.train429-create'),panel=root?.querySelectorAll('.train428-panel')?.[1];if(!panel)return;
    renderResources(root,panel);
    if(!root.querySelector('#trV3ResourceStrategy')){
      const field=document.createElement('label');field.className='field';
      field.innerHTML='<span>训练资源策略</span><select id="trV3ResourceStrategy" class="select"><option value="auto">自动调优（推荐）</option><option value="manual">手动：使用高级参数中的 batch / workers / cache</option></select><small>自动策略在后台按可用显存、CPU 和缓存空间解析参数；实际值与原因可在任务详情查看。</small>';
      panel.before(field);
      field.querySelector('select').value=state.trainingDraft?.resource?.strategy||'auto';
    }
    const s=splitState(),random=s.mode==='random_test_from_training_pool',labels=selectedLabels([...s.train]);
    panel.innerHTML=`<header><b>2. 本次训练素材</b><span>按图片选择，标签仅用于筛选</span></header><div class="train-v3-summary"><div><span>训练候选</span><b>${s.train.size} 张</b><em>${esc(labels.join('、')||'尚未选择')}</em></div><div><span>独立试验素材</span><b>${random?'随机抽取':s.test.size+' 张'}</b><em>${random?`${s.experiment}% / 每次重新抽取`:'与训练素材严格隔离'}</em></div><div><span>可选素材</span><b>${allCandidates().length} 张</b><em>已处理且已标注</em></div></div><div class="train-v3-mode"><label class="check"><input type="radio" name="trV3Mode" value="random_test_from_training_pool" ${random?'checked':''} onchange="setTrainSplitModeV3(this.value)"> 从本次训练素材随机抽取试验集</label><label class="check"><input type="radio" name="trV3Mode" value="independent_test_set" ${!random?'checked':''} onchange="setTrainSplitModeV3(this.value)"> 单独选择试验素材</label></div><div class="train-v3-actions"><button class="btn primary" onclick="openTrainMaterialPickerV3('train')">选择训练素材</button>${random?`<label class="field compact"><span>试验集比例</span><div class="input-suffix428"><input id="trV3Experiment" class="input" type="number" min="0.1" max="99.9" step="0.1" value="${s.experiment}"><span>%</span></div></label>`:`<button class="btn" onclick="openTrainMaterialPickerV3('test')">选择独立试验素材</button>`}<label class="field compact"><span>验证集比例</span><div class="input-suffix428"><input id="trV3Validation" class="input" type="number" min="0.1" max="99.9" step="0.1" value="${s.validation}"><span>%</span></div></label><button class="btn" onclick="trainQuality429()" ${s.train.size?'':'disabled'}>查看数据质量</button></div><small class="train-v3-note">每次打开默认全部不选。训练、验证和试验的最终图片名单会写入任务快照，可追溯且不会按数据集自动扩展。</small>`;
    // TrainingSubmitRuntime is the sole owner of submit-button readiness.
    // Legacy renderSplit must never write the disabled state from train428/train429 mirrors.
  }
  function pickerRows(){const p=state.trainMaterialPickerV3;if(!p)return[];const blocked=splitState().mode==='independent_test_set'?splitState()[otherRole(p.role)]:new Set();return(trainingApi()?.filterTrainingMaterials(state.images||[],{query:p.query,labelCodes:[...p.labels]})||[]).filter(row=>!blocked.has(imageId(row)))}
  function renderPicker(){
    const p=state.trainMaterialPickerV3,grid=document.getElementById('trV3Grid');if(!p||!grid)return;const rows=pickerRows(),pages=Math.max(1,Math.ceil(rows.length/p.pageSize));p.page=Math.min(Math.max(1,p.page),pages);const start=(p.page-1)*p.pageSize,current=rows.slice(start,start+p.pageSize);
    grid.innerHTML=current.map(row=>{const id=imageId(row),on=p.selected.has(id);return `<label class="train-v3-card ${on?'on':''}"><input type="checkbox" ${on?'checked':''} onchange="toggleTrainMaterialV3('${id}',this.checked,this)"><img src="${row.url}" loading="lazy" decoding="async"><b title="${esc(row.filename||'')}">${esc(row.filename||'')}</b><span>${esc((row.labels||[]).map(labelText).join('、')||'无标签')}</span></label>`}).join('')||'<div class="empty">没有符合筛选条件的可训练图片</div>';
    const count=document.getElementById('trV3PickerCount');if(count)count.textContent=`筛选结果 ${rows.length} 张 · 已选 ${p.selected.size} 张`;
    const pager=document.getElementById('trV3Pager');if(pager)pager.innerHTML=`<button class="btn mini" ${p.page<=1?'disabled':''} onclick="trainMaterialPageV3(-1)">上一页</button><span>${p.page} / ${pages}</span><button class="btn mini" ${p.page>=pages?'disabled':''} onclick="trainMaterialPageV3(1)">下一页</button>`;
  }
  window.openTrainMaterialPickerV3=async function(role){
    // The legacy V3 selector still pages locally. Load its pool only when opened,
    // including when training was launched from the algorithm list.
    const fetchPool=window.__materialPaging61?.originalFetch||window.fetch.bind(window);
    const response=await fetchPool(`/api/projects/${pid()}/images`);
    if(!response.ok)return toast('训练素材读取失败，请重试');
    state.images=await response.json();
    state.trainMaterialPickerV3={role,selected:new Set(),labels:new Set(),query:'',page:1,pageSize:80};
    modal(role==='train'?'选择本次训练素材':'选择独立试验素材',`<div class="train-v3-picker"><header><div><b>${role==='train'?'训练候选素材':'独立试验素材'}</b><span>只有明确勾选的图片会进入本次任务</span></div><strong id="trV3PickerCount"></strong></header><div class="train-v3-filter"><input id="trV3Q" class="input" placeholder="搜索图片名称" oninput="trainMaterialSearchV3(this.value)"><div id="trV3Chips" class="data426-chips"><button class="data426-chip clear on" data-label="" onclick="clearTrainMaterialLabelsV3()">全部标签</button>${(state.labels||[]).map(row=>`<button class="data426-chip" data-label="${esc(row.code)}" onclick="toggleTrainMaterialLabelV3('${esc(row.code)}')">${esc(row.display_name||row.code)}</button>`).join('')}</div></div><div class="picker412-actions train-v3-batch"><button class="btn mini" onclick="trainMaterialSelectV3('select-filtered')">选择当前筛选结果</button><button class="btn mini" onclick="trainMaterialSelectV3('invert-filtered')">反选当前筛选结果</button><button class="btn mini" onclick="trainMaterialSelectV3('select-all')">全选全部可用素材</button><button class="btn mini" onclick="trainMaterialSelectV3('clear-all')">全部不选</button></div><div id="trV3Grid" class="train-v3-grid"></div><div id="trV3Pager" class="data426-pager"></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="confirmTrainMaterialPickerV3()">确认选择</button></div></div>`,true);setTimeout(renderPicker,20)
  };
  window.trainMaterialSearchV3=value=>{const p=state.trainMaterialPickerV3;if(!p)return;p.query=String(value||'');p.page=1;renderPicker()};
  window.toggleTrainMaterialLabelV3=function(code){const p=state.trainMaterialPickerV3;if(!p)return;p.labels.has(code)?p.labels.delete(code):p.labels.add(code);p.page=1;document.querySelectorAll('#trV3Chips .data426-chip').forEach(button=>button.classList.toggle('on',button.dataset.label?p.labels.has(button.dataset.label):!p.labels.size));renderPicker()};
  window.clearTrainMaterialLabelsV3=()=>{const p=state.trainMaterialPickerV3;if(!p)return;p.labels.clear();p.page=1;document.querySelectorAll('#trV3Chips .data426-chip').forEach(button=>button.classList.toggle('on',!button.dataset.label));renderPicker()};
  window.toggleTrainMaterialV3=(id,on,checkbox)=>{const p=state.trainMaterialPickerV3;if(!p)return;on?p.selected.add(String(id)):p.selected.delete(String(id));checkbox?.closest('.train-v3-card')?.classList.toggle('on',!!on);const count=document.getElementById('trV3PickerCount');if(count)count.textContent=`筛选结果 ${pickerRows().length} 张 · 已选 ${p.selected.size} 张`};
  window.trainMaterialSelectV3=function(action){const p=state.trainMaterialPickerV3;if(!p)return;const filtered=pickerRows().map(imageId),eligible=eligibleFor(p.role).map(imageId);p.selected=new Set(trainingApi().applyMaterialSelection([...p.selected],filtered,eligible,action));renderPicker()};
  window.trainMaterialPageV3=delta=>{const p=state.trainMaterialPickerV3;if(!p)return;p.page=Math.max(1,p.page+Number(delta||0));renderPicker()};
  window.confirmTrainMaterialPickerV3=function(){
    const p=state.trainMaterialPickerV3;if(!p)return;
    if(!window.TrainingDraftRuntime?.update)return toast('训练草稿模块尚未加载，请刷新后重试');
    const current=splitState(),selected=[...p.selected].map(String),selectedSet=new Set(selected);
    const patch=p.role==='test'?{materialIds:[...current.train].filter(id=>!selectedSet.has(String(id))),testMaterialIds:selected}:{materialIds:selected,testMaterialIds:[...current.test].filter(id=>!selectedSet.has(String(id)))};
    window.TrainingDraftRuntime.update(patch);closeModal();setTimeout(renderSplit,20)
  };
  window.setTrainSplitModeV3=mode=>{
    if(!window.TrainingDraftRuntime?.update)return toast('训练草稿模块尚未加载，请刷新后重试');
    const splitMode=mode==='independent_test_set'?'independent_test_set':'random_test_from_training_pool';
    window.TrainingDraftRuntime.update({splitMode,...(splitMode==='independent_test_set'?{}:{testMaterialIds:[]})});renderSplit()
  };
  window.startAlgorithmTraining429=async function(aid){
    if(!state.uiReady&&window.__v53InitPromise)await window.__v53InitPromise;
    if(!(state.targets||[]).some(target=>target.status==='ready')){
      const options=await api(`/api/training_options?project_id=${pid()}`);
      state.targets=options?.targets||[];
    }
    try{state.trainingDevicesV3=await api('/api/v62/training-devices')}catch(error){state.trainingDevicesV3={options:[],error:String(error.message||error)}}
    const result=await previousStart?.(aid);const recommendedDevice=state.trainingDevicesV3.recommended||'auto';window.TrainingDraftRuntime?.update?.({resource:{device:recommendedDevice}});const deviceSelect=document.getElementById('trV3Device');if(deviceSelect)deviceSelect.value=recommendedDevice;[40,140,340,650].forEach(delay=>setTimeout(renderSplit,delay));return result
  };
    const historicalLog=window.showTrainLog423;
  window.showTrainLog423=async function(id){
    try{
      const job=await api(`/api/projects/${pid()}/jobs/${id}`);
      if(!job.task_id)return historicalLog?.(id);
      const e=job.device_evidence||{},r=job.resolved_resources||{},m=job.runtime_metrics||{},args=job.actual_train_params||{},diagnosis=m.diagnostic||{};
      const labels={memory_pressure_oom:'显存不足，已触发 OOM',cpu_bottleneck:'CPU 供给不足',io_bottleneck:'数据读取受限',gpu_saturated:'GPU 持续繁忙',insufficient_samples:'采样不足',unknown:'暂无足够证据'};
      const rows=[['请求设备',job.requested_device],['分配设备',job.assigned_device],['实际设备',job.actual_device],['GPU 名称',e.gpu_name],['GPU UUID',e.gpu_uuid],['GPU 索引',e.gpu_index],['进程 PID',e.pid],['Torch / CUDA',`${e.torch_version||'—'} / ${e.cuda_version||'—'}`],['实际 batch',args.batch??r.resolved_batch],['实际 workers',args.workers??r.resolved_workers],['实际 cache',args.cache??r.resolved_cache],['运行诊断',labels[diagnosis.code]||diagnosis.code||'等待采样']];
      const log=await safe(api(`/api/projects/${pid()}/jobs/${id}/log`))||'';
      modal('训练运行中心',`<div class="trainlog428"><h2>${esc(job.message||job.status||'等待执行')}</h2><p>Epoch ${esc(String(job.current_epoch||0))} / ${esc(String(job.total_epochs||job.epochs||'—'))}</p><table class="table"><tbody>${rows.map(([label,value])=>`<tr><th>${esc(label)}</th><td>${esc(value==null?'尚未产生':String(value))}</td></tr>`).join('')}</tbody></table><p>${esc((r.reasons||[]).join('；'))}</p><details><summary>工程师技术日志</summary><pre class="log">${esc(log)}</pre></details><div class="row end"><button class="btn" onclick="showTrainLog423('${id}')">刷新</button><button class="btn" onclick="closeModal()">关闭</button></div></div>`,true);
    }catch(error){toast(error.message||error)}
  };
})();

/* Stable single-instance manual/batch annotation workbench. */
(()=>{
  const workbenchApi=()=>window.PlatformCore?.annotationWorkbench;
  const queueIds=()=>Array.isArray(state.annotationQueue414)&&state.annotationQueue414.length?state.annotationQueue414.map(String):state.activeImage?[String(state.activeImage.id)]:[];
  const imageById=id=>(state.images||[]).find(x=>String(x.id)===String(id));
  const preload=url=>new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(true);image.onerror=()=>reject(new Error('图片加载失败'));image.src=url});

  function ensureShell(){
    if(document.querySelector('.ann420-stable'))return;
    modal('图片标注',`<div class="ann-layout pro ann414 ann417 ann420-stable"><aside class="ann417-queue"><header><b>连续标注</b><span id="ann420Position">1 / 1</span></header><div id="ann420Queue"></div></aside><div class="ann-work"><div class="ann-toolbar"><button id="ann414Save" class="btn primary small" onclick="saveAnn(false)">保存并继续</button><label class="ann417-label"><span>绘制标签</span><select id="ann420Label" class="select" onchange="state.activeLabel=Number(this.value);renderAnnSide()"></select></label><button id="ann420Prev" class="btn small">上一张</button><button id="ann420Next" class="btn small">下一张</button><button class="btn small" onclick="undoAnn()">撤销</button><button class="btn small" onclick="redoAnn()">重做</button><button class="btn small danger" onclick="deleteActiveBox()">删除框</button><span class="ann414-state"><span id="ann420Filename"></span> · <b id="annSaveState">已保存</b></span><div class="ann-zoom"><button class="btn mini" onclick="zoomAnn(-0.1)">-</button><span id="zoomText">100%</span><button class="btn mini" onclick="zoomAnn(0.1)">+</button></div></div><div class="ann-canvas-wrap"><div id="annStage" class="ann-stage" style="transform:scale(1);transform-origin:top center"><img id="annImg" alt="当前标注图片"></div></div></div><aside class="side-panel ann-side"><div class="side-section"><div class="side-title">标注框 <span id="ann420BoxCount">0</span></div><div id="annBoxes"></div></div><div class="hint-card">标签统一来自“配置中心 → 标签管理”。拖拽新建框；切换图片前自动保存；画布和弹窗不会重复创建。</div></aside></div>`,true);
  }

  function updateShell(){
    const image=state.activeImage;if(!image)return;ensureShell();
    const ids=queueIds(),at=Math.max(0,ids.indexOf(String(image.id))),visible=workbenchApi()?.queueWindow(ids,String(image.id),9)||ids;
    const queue=document.getElementById('ann420Queue');
    if(queue)queue.innerHTML=visible.map(id=>{const row=imageById(id);return row?`<button class="${id===String(image.id)?'active':''}" onclick="goAnnotation417('${id}')"><img src="${row.url}" loading="lazy" decoding="async"><span><b>${esc(row.filename)}</b><em>${row.annotated?`${row.box_count||0} 框`:'待标注'}</em></span></button>`:''}).join('');
    const position=document.getElementById('ann420Position');if(position)position.textContent=`${at+1} / ${ids.length}`;
    const filename=document.getElementById('ann420Filename');if(filename)filename.textContent=image.filename||'';
    const select=document.getElementById('ann420Label');if(select)select.innerHTML=(state.labels||[]).map(label=>`<option value="${Number(label.class_id)}" ${Number(state.activeLabel)===Number(label.class_id)?'selected':''}>${esc(label.display_name||label.code)} · ${esc(label.code)}</option>`).join('');
    const previous=document.getElementById('ann420Prev'),next=document.getElementById('ann420Next');
    if(previous){previous.disabled=at<=0;previous.onclick=()=>at>0&&goAnnotation417(ids[at-1])}
    if(next){next.disabled=at>=ids.length-1;next.onclick=()=>at<ids.length-1&&goAnnotation417(ids[at+1])}
    const count=document.getElementById('ann420BoxCount');if(count)count.textContent=String(state.ann?.boxes?.length||0);
    const img=document.getElementById('annImg');if(img&&img.src!==new URL(image.url,location.href).href)img.src=image.url;
    const stage=document.getElementById('annStage');if(stage){stage.style.transform=`scale(${state.annZoom||1})`;stage.classList.toggle('disabled',!(state.labels||[]).length)}
    requestAnimationFrame(()=>{drawBoxes();if((state.labels||[]).length)bindAnnotationEvents();renderAnnSide()});
  }

  function ensureWorkbench(){
    if(state.annotationWorkbench)return state.annotationWorkbench;
    const api=workbenchApi();if(!api)return null;
    state.annotationWorkbench=api.createAnnotationWorkbench({
      load:async id=>{
        const image=imageById(id);if(!image)throw new Error('图片不存在或尚未加载');
        if(!(state.labels||[]).length&&typeof refreshLabels414==='function')await refreshLabels414(false);
        const [response]=await Promise.all([apiRequestAnnotation420(id),preload(image.url)]);
        return {image:response?.image||image,annotation:response?.annotation||{boxes:[]}};
      },
      save:async()=>window.saveAnn(true),
      apply:value=>{
        state.activeImage=value.image;state.ann=value.annotation||{boxes:[]};if(!Array.isArray(state.ann.boxes))state.ann.boxes=[];
        const first=(state.labels||[]).find(label=>state.ann.boxes.some(box=>Number(box.class_id)===Number(label.class_id)))||(state.labels||[])[0];
        state.activeLabel=first?.class_id??null;state.activeBox=null;state.annZoom=1;state.annDirty=false;state.annHistory=[];state.annRedo=[];updateShell();
      }
    });
    return state.annotationWorkbench;
  }

  async function apiRequestAnnotation420(id){return api(`/api/projects/${pid()}/annotations/${id}`)}
  window.openAnnotation=async function(id){
    const key=String(id);if(!imageById(key))return toast('图片不存在或尚未加载');
    if(!Array.isArray(state.annotationQueue414)||!state.annotationQueue414.some(value=>String(value)===key))state.annotationQueue414=[key];
    try{return await ensureWorkbench()?.open(key)}catch(error){toast(`打开标注失败：${error.message||error}`);return false}
  };
  window.goAnnotation417=id=>window.openAnnotation(id);
  window.renderAnnotator=updateShell;

  const previousMarkDirty=window.markDirty;
  window.markDirty=function(){state.annotationWorkbench?.markDirty();return previousMarkDirty?.()};
  const previousSave=window.saveAnn;
  window.saveAnn=async function(silent=false){
    const savedId=String(state.activeImage?.id||''),ok=await previousSave?.(silent);
    if(ok){state.annotationWorkbench?.markSaved();patchMaterialCard412(state.activeImage)}
    if(ok&&!silent){const ids=queueIds(),at=ids.indexOf(savedId);if(at>=0&&at<ids.length-1)await state.annotationWorkbench?.open(ids[at+1])}
    return ok;
  };

  window.patchMaterialCard412=function(image){
    if(!image)return;const cards=[...document.querySelectorAll('.data412-card,.data429-card')],card=cards.find(node=>node.querySelector('.data426-title')?.textContent===String(image.filename||''));if(!card)return;
    const meta=card.querySelectorAll('.data426-meta span');if(meta[1])meta[1].textContent=image.annotated?`已标注 · ${image.box_count||0}框`:'待标注';
    const tags=card.querySelector('.data426-tags');if(tags)tags.innerHTML=(image.labels||[]).map(label=>`<span>${esc(typeof displayLabel412==='function'?displayLabel412(label):label)}</span>`).join('')||'<em>暂无标签</em>';
    const stage=card.querySelector('.data411-stage');if(stage){stage.querySelectorAll('.data412-box,.data411-box').forEach(node=>node.remove());const width=Number(image.width||1),height=Number(image.height||1);stage.insertAdjacentHTML('beforeend',(image.annotation_preview||[]).slice(0,24).map(box=>`<i class="data412-box" style="left:${100*Number(box.x1||0)/width}%;top:${100*Number(box.y1||0)/height}%;width:${100*Math.max(0,Number(box.x2||0)-Number(box.x1||0))/width}%;height:${100*Math.max(0,Number(box.y2||0)-Number(box.y1||0))/height}%"><em>${esc(typeof displayLabel412==='function'?displayLabel412(box.label):box.label||'')}</em></i>`).join(''))}
  };

  const previousClose=window.closeModal;
  window.closeModal=async function(){
    const layers=[...document.querySelectorAll('.v424-modal-layer')],top=layers.at(-1);
    if(top?.querySelector('.ann420-stable')&&state.annotationWorkbench?.dirty){const ok=await window.saveAnn(true);if(!ok)return false}
    if(top?.querySelector('.ann420-stable')){state.annotationWorkbench?.invalidate();state.annotationWorkbench=null;state.annotationQueue414=[];state.activeImage=null}
    return previousClose?.();
  };
})();

/* Persistent v60 AI annotation UI: real worker progress, durable review, no HTTP-thread inference. */
(()=>{
  const previousShowTask=window.showTaskProgress427;
  const previousRenderOps=window.renderOps427;
  const taskApi=id=>`/api/v60/projects/${pid()}/annotation-tasks${id?`/${id}`:''}`;
  const taskView=task=>window.PlatformCore?.annotationTasks?.annotationTaskView(task)||{};
  const imageById=id=>(state.images||[]).find(image=>String(image.id)===String(id));
  const time=value=>{if(!value)return '-';const date=new Date(value);return Number.isNaN(date.getTime())?'-':date.toLocaleString()};
  const elapsed=task=>{const start=Date.parse(task.created_at||''),end=Date.parse(task.finished_at||task.updated_at||'');return Number.isFinite(start)&&Number.isFinite(end)?fmtTime424(Math.max(0,(end-start)/1000)):'-'};

  function applyTaskResult(result){
    for(const summary of result.image_summaries||[]){
      const image=imageById(summary.image_id);if(!image)continue;
      image.box_count=Number(summary.box_count)||0;image.annotated=image.box_count>0;image.labels=summary.labels||[];
      if(image.annotated)image.processing_status='processed';
      try{patchMaterialCard412(image)}catch(_){}
    }
  }

  function progressShell(task){
    modal('AI自动标注任务',`<div class="wait427 ai60-progress" data-task-id="${esc(task.id)}"><div class="wait427-anim"><i></i><i></i><i></i><b id="ai60Status"></b></div><div class="wait427-progress"><i id="ai60Bar"></i></div><div class="wait427-stats"><span>真实进度 <b id="ai60Percent">0%</b></span><span>已完成 <b id="ai60Counts">0 / 0</b></span><span>失败 <b id="ai60Failed">0</b></span><span>耗时 <b id="ai60Elapsed">-</b></span></div><div class="alert soft"><b>当前图片</b><span id="ai60Current">等待 Worker 领取任务</span></div><div id="ai60Error"></div><div id="ai60Actions" class="row end"></div></div>`,true);
  }

  function renderProgress(task){
    const root=document.querySelector(`.ai60-progress[data-task-id="${CSS.escape(String(task.id))}"]`);if(!root)return;
    const view=taskView(task),set=(id,value)=>{const node=root.querySelector(`#${id}`);if(node)node.textContent=value};
    set('ai60Status',view.statusText);set('ai60Percent',`${Number(view.percent||0).toFixed(1)}%`);set('ai60Counts',view.progressText);set('ai60Failed',view.failed);set('ai60Elapsed',elapsed(task));
    const bar=root.querySelector('#ai60Bar');if(bar)bar.style.width=`${view.percent||0}%`;
    const current=imageById(task.current_item);set('ai60Current',current?.filename||task.current_item||'等待 Worker 处理');
    const error=root.querySelector('#ai60Error');if(error)error.innerHTML=view.error?`<div class="error-box422"><b>失败原因</b><span>${esc(view.error)}</span></div>`:'';
    const actions=root.querySelector('#ai60Actions');if(actions)actions.innerHTML=`${view.canCancel?`<button class="btn danger" onclick="cancelAiTask60('${task.id}')">取消任务</button>`:''}${view.canReview?`<button class="btn primary" onclick="reviewAiLabel427('${task.id}')">审核候选结果</button>`:''}${view.canRetry?`<button class="btn" onclick="retryAiTask60('${task.id}')">重试</button>`:''}<button class="btn" onclick="closeModal()">关闭</button>`;
    if(state.page==='自动标注及清洗')renderAiTaskRows60(state.annotationTasks60||[]);
  }

  window.showAiTask60=async function(id){
    try{
      const first=await api(taskApi(id));progressShell(first);renderProgress(first);
      state.ai60Pollers=state.ai60Pollers||{};state.ai60Pollers[id]?.stop?.();
      const poller=window.PlatformCore?.taskPoller?.createTaskPoller({load:()=>api(taskApi(id)),onUpdate:renderProgress,onError:error=>{const node=document.querySelector(`.ai60-progress[data-task-id="${CSS.escape(String(id))}"] #ai60Error`);if(node)node.innerHTML=`<div class="error-box422">${esc(error.message||error)}</div>`}});
      state.ai60Pollers[id]=poller;await poller?.start();
    }catch(error){toast(error.message||error)}
  };
  window.showTaskProgress427=function(type,id){return type==='label'?showAiTask60(id):previousShowTask?.(type,id)};
  window.cancelAiTask60=async id=>{try{const task=await api(`${taskApi(id)}/cancel`,{method:'POST'});renderProgress(task)}catch(error){toast(error.message||error)}};
  window.retryAiTask60=async id=>{try{const task=await api(`${taskApi(id)}/retry`,{method:'POST'});closeModal();showAiTask60(task.id)}catch(error){toast(error.message||error)}};

  function normalizedLabelText(value){
    const parts=String(value||'').split(/[、,，;；\n\t]+/).map(item=>item.trim()).filter(Boolean);
    return [...new Set(parts.map(value=>{const match=(state.labels||[]).find(label=>[label.code,label.display_name,label.display_name_zh].some(item=>String(item||'').trim()===value));return match?.code||value}))].join('、');
  }
  window.submitAiLabel429=async function(ids=[]){
    if(!ids.length)return toast('没有需要标注的图片');
    const model=(state.modelConfigs||[]).find(item=>item.default_for_annotation)||(state.modelConfigs||[])[0];
    const body={image_ids:ids.map(String),labels_text:normalizedLabelText(document.getElementById('ai429Labels')?.value||''),reference_image_ids:[...(state.ai429RefSelected||new Set())].map(String),threshold:+document.getElementById('ai429Threshold')?.value||.45,overwrite:!!document.getElementById('ai429Overwrite')?.checked,task_name:`AI自动标注-${new Date().toLocaleString()}`,model_config_id:model?.id||null};
    try{const task=await api(taskApi(),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});closeModal();showAiTask60(task.id)}catch(error){toast(error.message||error)}
  };

  function taskRow(task){
    const view=taskView(task),labels=(task.requested_labels||[]).map(code=>typeof displayLabel412==='function'?displayLabel412(code):code).join('、')||'-';
    return `<tr data-task-id="${esc(task.id)}"><td><b>${esc(task.name||task.id)}</b><div class="muted-line">${esc(labels)}</div></td><td><span class="pill ${view.active?'run':view.status==='AWAITING_CONFIRMATION'?'warn':view.status==='SUCCEEDED'?'ok':view.status==='FAILED'?'err':''}">${esc(view.statusText)}</span></td><td><div class="op427-progress"><i><em style="width:${view.percent}%"></em></i><span>${esc(view.progressText)} · ${Number(view.percent||0).toFixed(1)}%</span></div></td><td>${view.boxes}</td><td>${time(task.created_at)}<div class="muted-line">${elapsed(task)}</div></td><td><div class="row"><button class="btn mini" onclick="showAiTask60('${task.id}')">详情</button>${view.canReview?`<button class="btn mini primary" onclick="reviewAiLabel427('${task.id}')">审核</button>`:''}${view.canRetry?`<button class="btn mini" onclick="retryAiTask60('${task.id}')">重试</button>`:''}</div></td></tr>`;
  }
  function renderAiTaskRows60(tasks){const body=document.getElementById('ai60TaskRows');if(body)body.innerHTML=tasks.map(taskRow).join('')||'<tr><td colspan="6">暂无AI标注任务</td></tr>'}
  window.renderOps427=async function(){
    if((state.v427OpsTab||'label')==='clean'){window.AutoLabelPollRuntime?.deactivate?.();return previousRenderOps?.()}
    try{
      const response=await api(`${taskApi()}?limit=50`);state.annotationTasks60=response.items||[];
      document.getElementById('view').innerHTML=`<section class="ops427"><div class="ops427-head"><div class="seg"><button class="on" onclick="state.v427OpsTab='label';renderOps427()">AI自动标注</button><button onclick="state.v427OpsTab='clean';renderOps427()">自动清洗</button></div><button class="btn primary" onclick="createAiLabel427()">＋ 创建AI标注任务</button></div><section class="panel"><div class="table-wrap"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>真实处理进度</th><th>候选框</th><th>创建/耗时</th><th>操作</th></tr></thead><tbody id="ai60TaskRows"></tbody></table></div></section></section>`;
      renderAiTaskRows60(state.annotationTasks60);
      window.AutoLabelPollRuntime?.activate?.(state.annotationTasks60);
    }catch(error){document.getElementById('view').innerHTML=`<div class="error-box422">${esc(error.message||error)}</div>`}
  };

  function candidateOverlay(box,image){
    const width=Number(image?.width||1),height=Number(image?.height||1),x=100*Number(box.x1||0)/width,y=100*Number(box.y1||0)/height,w=100*Math.max(0,Number(box.x2||0)-Number(box.x1||0))/width,h=100*Math.max(0,Number(box.y2||0)-Number(box.y1||0))/height;
    return `<i class="data412-box" style="left:${x}%;top:${y}%;width:${w}%;height:${h}%"><em>${esc(typeof displayLabel412==='function'?displayLabel412(box.label):box.label||'')}</em></i>`;
  }
  function ensureReviewShell(){
    if(document.querySelector('.ai60-review'))return;
    modal('AI待确认标注',`<div class="review427 ai60-review"><div class="review427-top"><div><b>候选结果不会自动写入正式标注</b><span id="ai60ReviewSummary"></span></div><div class="row"><button class="btn mini" onclick="reviewPageSelect60(true)">本页全选</button><button class="btn mini" onclick="reviewPageSelect60(false)">本页全不选</button></div></div><div id="ai60ReviewGrid" class="review427-grid"></div><div class="row between"><div id="ai60ReviewPager"></div><div class="row"><button class="btn" onclick="completeAiReview60('reject')">全部拒绝</button><button class="btn" onclick="completeAiReview60('partial')">采用已勾选</button><button class="btn primary" onclick="completeAiReview60('accept')">全部接受</button><button class="btn" onclick="closeModal()">暂不处理</button></div></div></div>`,true);
  }
  function renderReviewPage(){
    const review=state.ai60Review;if(!review)return;ensureReviewShell();
    const summary=document.getElementById('ai60ReviewSummary');if(summary)summary.textContent=`第 ${review.offset+1}–${Math.min(review.total,review.offset+review.items.length)} / ${review.total} 张；失败素材不可采用`;
    const grid=document.getElementById('ai60ReviewGrid');if(grid)grid.innerHTML=review.items.map(item=>{const image=imageById(item.image_id)||item,reviewable=item.status!=='failed',checked=review.decisions.get(String(item.image_id))===true;return `<label class="review427-card ${reviewable?'':'failed'}"><input type="checkbox" ${checked?'checked':''} ${reviewable?'':'disabled'} onchange="toggleAiDecision60('${item.image_id}',this.checked)"><div class="review427-img ai-candidate-stage"><img src="${esc(item.url||image.url||'')}" loading="lazy" decoding="async">${(item.boxes||[]).map(box=>candidateOverlay(box,image)).join('')}<strong>${item.status==='failed'?'处理失败':`${(item.boxes||[]).length} 个候选框`}</strong></div><b>${esc(item.filename||image.filename||item.image_id)}</b><div>${item.error?`<span class="err">${esc(item.error)}</span>`:[...new Set((item.boxes||[]).map(box=>box.label))].map(label=>`<span>${esc(typeof displayLabel412==='function'?displayLabel412(label):label)}</span>`).join('')||'<span>未检测到目标</span>'}</div>${reviewable?`<button type="button" class="btn mini" onclick="event.preventDefault();event.stopPropagation();editAiCandidate60('${item.image_id}')">编辑候选框</button>`:''}</label>`}).join('');
    const pager=document.getElementById('ai60ReviewPager');if(pager)pager.innerHTML=`<button class="btn mini" ${review.offset<=0?'disabled':''} onclick="aiReviewPage60(-1)">上一页</button><span>${Math.floor(review.offset/review.limit)+1} / ${Math.max(1,Math.ceil(review.total/review.limit))}</span><button class="btn mini" ${review.offset+review.items.length>=review.total?'disabled':''} onclick="aiReviewPage60(1)">下一页</button>`;
  }
  async function loadReviewPage(offset){const review=state.ai60Review,response=await api(`${taskApi(review.id)}/candidates?limit=${review.limit}&cursor=${Math.max(0,offset)}`);review.offset=Math.max(0,offset);review.total=response.total||0;review.items=response.items||[];for(const item of review.items){review.seen.set(String(item.image_id),item);if(item.status!=='failed'&&!review.decisions.has(String(item.image_id)))review.decisions.set(String(item.image_id),item.accepted===false?false:true)}renderReviewPage()}
  window.reviewAiLabel427=async function(id){try{state.ai60Review={id:String(id),offset:0,limit:24,total:0,items:[],decisions:new Map(),edits:new Map(),seen:new Map()};await loadReviewPage(0)}catch(error){toast(error.message||error)}};
  window.aiReviewPage60=async direction=>{const review=state.ai60Review;if(!review)return;try{await loadReviewPage(review.offset+direction*review.limit)}catch(error){toast(error.message||error)}};
  window.toggleAiDecision60=(id,accepted)=>state.ai60Review?.decisions.set(String(id),!!accepted);
  window.reviewPageSelect60=accepted=>{const review=state.ai60Review;if(!review)return;for(const item of review.items)if(item.status!=='failed')review.decisions.set(String(item.image_id),!!accepted);renderReviewPage()};
  function renderCandidateEditor60(){
    const edit=state.ai60Edit,review=state.ai60Review,item=review?.seen.get(edit?.id),image=imageById(edit?.id)||item;if(!edit||!item)return;
    if(!document.querySelector('.ai60-edit'))modal('编辑AI候选框','<div class="ai60-edit"><div id="ai60EditStage" class="data412-previewstage"></div><div id="ai60EditRows" class="form"></div><div class="row between"><button class="btn" onclick="addAiCandidateBox60()">＋ 添加框</button><div class="row"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="saveAiCandidateEdit60()">保存候选修改</button></div></div></div>',true);
    const stage=document.getElementById('ai60EditStage');if(stage)stage.innerHTML=`<img src="${esc(item.url||image?.url||'')}">${edit.boxes.map(box=>candidateOverlay(box,image)).join('')}`;
    const rows=document.getElementById('ai60EditRows');if(rows)rows.innerHTML=edit.boxes.map((box,index)=>`<div class="form six ai60-edit-row"><div class="field"><label>标签</label><select class="select" onchange="updateAiCandidateBox60(${index},'label',this.value)">${(state.labels||[]).map(label=>`<option value="${esc(label.code)}" ${String(label.code)===String(box.label)?'selected':''}>${esc(label.display_name||label.code)} · ${esc(label.code)}</option>`).join('')}</select></div>${['x1','y1','x2','y2'].map(key=>`<div class="field"><label>${key}</label><input class="input" type="number" value="${Number(box[key]||0)}" onchange="updateAiCandidateBox60(${index},'${key}',this.value)"></div>`).join('')}<div class="field"><label>操作</label><button class="btn danger" onclick="deleteAiCandidateBox60(${index})">删除</button></div></div>`).join('')||'<div class="empty">当前没有候选框，可点击“添加框”。</div>';
  }
  window.editAiCandidate60=id=>{const item=state.ai60Review?.seen.get(String(id));if(!item)return;state.ai60Edit={id:String(id),boxes:(item.boxes||[]).map(box=>({...box}))};renderCandidateEditor60()};
  window.updateAiCandidateBox60=(index,key,value)=>{const box=state.ai60Edit?.boxes?.[index];if(!box)return;if(key==='label'){const label=(state.labels||[]).find(item=>String(item.code)===String(value));box.label=String(value);box.class_id=label?.class_id??box.class_id}else box[key]=Number(value);renderCandidateEditor60()};
  window.deleteAiCandidateBox60=index=>{state.ai60Edit?.boxes?.splice(index,1);renderCandidateEditor60()};
  window.addAiCandidateBox60=()=>{const edit=state.ai60Edit,image=imageById(edit?.id)||state.ai60Review?.seen.get(edit?.id),label=(state.labels||[])[0],width=Number(image?.width||100),height=Number(image?.height||100);if(!edit)return;edit.boxes.push({id:`manual-${Date.now()}`,label:label?.code||'',class_id:label?.class_id??0,x1:width*.1,y1:height*.1,x2:width*.3,y2:height*.3,confidence:1,source:'ai_candidate_reviewed'});renderCandidateEditor60()};
  window.saveAiCandidateEdit60=()=>{const edit=state.ai60Edit;if(!edit)return;const invalid=edit.boxes.some(box=>!['x1','y1','x2','y2'].every(key=>Number.isFinite(Number(box[key])))||Number(box.x2)<=Number(box.x1)||Number(box.y2)<=Number(box.y1)||!String(box.label||''));if(invalid)return toast('候选框坐标或标签无效，请检查');const item=state.ai60Review.seen.get(edit.id);item.boxes=edit.boxes.map(box=>({...box}));state.ai60Review.edits.set(edit.id,item.boxes);state.ai60Review.decisions.set(edit.id,true);closeModal();renderReviewPage()};
  window.completeAiReview60=async mode=>{
    const review=state.ai60Review;if(!review)return;
    const decisions=mode==='partial'?[...review.decisions].map(([image_id,accepted])=>({image_id,accepted,...(review.edits.has(image_id)?{boxes:review.edits.get(image_id)}:{})})):[];
    const body={decisions,reject_unmentioned:mode!=='accept',accept_unmentioned:mode==='accept',commit:true};
    try{const result=await api(`${taskApi(review.id)}/decisions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});applyTaskResult(result);closeModal();toast(mode==='reject'?'本次AI结果已拒绝，正式标注未被修改':`已采用 ${result.applied_images||0} 张，写入 ${result.boxes_added||0} 个框`);if(state.page==='自动标注及清洗')renderOps427()}catch(error){toast(error.message||error)}
  };
  window.confirmAiLabel427=id=>completeAiReview60('partial');
})();

/* Persistent deployment tests: upload returns immediately and a Worker performs real Runtime inference. */
(()=>{
  const previousResult=window.renderDetectionResult;
  window.renderDetectionResult=function(result,title){
    const html=previousResult?.(result,title)||'',metrics=`<div class="report429-kpis"><div><span>预处理</span><b>${Number(result?.preprocess_ms||0).toFixed(2)} ms</b></div><div><span>模型推理</span><b>${Number(result?.inference_ms||0).toFixed(2)} ms</b></div><div><span>后处理</span><b>${Number(result?.postprocess_ms||0).toFixed(2)} ms</b></div><div><span>任务总耗时</span><b>${Number(result?.total_elapsed_ms||result?.elapsed_ms||0).toFixed(2)} ms</b></div></div>`;
    return html+metrics;
  };
  window.benchPredictOne=async function(selectId,file,conf){
    if(!file)throw new Error('请选择测试图片');const select=document.getElementById(selectId),model=(state.testModels||[])[Number(select?.value)];if(!model)throw new Error('请选择可用测试模型');
    const format=String(model.runtime_format||String(model.path||'').split('.').pop()||'').toLowerCase(),vendor=['rknn','om','bmodel'].includes(format),framework=model.framework||'ultralytics';
    const env=vendor?{}:(state.inferenceEnvs||[]).find(item=>item.framework===framework&&item.status==='ready');if(!vendor&&!env)throw new Error(`当前没有可用的${framework==='paddle'?'Paddle':'Ultralytics'} Runtime`);
    const form=new FormData();form.append('file',file);form.append('model_name',model.model_name||model.path||'');form.append('model_source',model.model_source||'project');form.append('local_path',model.path||'');form.append('algorithm_id',model.algorithm_id||'');form.append('version_id',model.version_id||'');form.append('conf',conf||.25);form.append('inference_framework',framework);form.append('inference_env_id',env?.id||'');
    let task=await api(`/api/v61/projects/${pid()}/deployment-tests`,{method:'POST',body:form}),attempt=0;
    while(['QUEUED','RUNNING','CANCEL_REQUESTED'].includes(task.status)&&attempt++<700){const output=document.getElementById('benchResult');if(output)output.innerHTML=`<div class="loading">真实 Runtime 测试中 · ${esc(task.stage||task.status)} · ${Number(task.progress||0).toFixed(1)}%</div>`;await new Promise(resolve=>setTimeout(resolve,900));task=await api(`/api/v61/projects/${pid()}/deployment-tests/${task.id}`)}
    if(task.status!=='SUCCEEDED')throw new Error(task.error||`部署测试未通过：${task.status}`);return {r:task.result||{},m:model,env};
  };
})();

/* Activate the storage UI after every legacy compatibility layer has loaded. */
(()=>{
  const storageApi=()=>window.PlatformCore?.storage;
  const finalNav=renderNav;
  renderNav=function(){
    finalNav();
    if(!state.v427Advanced)return;
    const resource=[...document.querySelectorAll('#nav .nav-group')].find(group=>group.querySelector('.nav-group-title')?.textContent.trim()==='资源配置');
    if(resource&&!resource.querySelector('[data-storage-nav="1"]'))resource.insertAdjacentHTML('beforeend',`<button data-storage-nav="1" class="nav-btn ${state.page==='素材存储配置'?'active':''}" onclick="setPage('素材存储配置')"><span class="nav-left"><i>▣</i><b>素材存储配置</b></span><span class="nav-arrow">›</span></button>`);
  };
  const finalDataset=window.renderDatasets424;
  window.renderDatasets424=function(){
    const all=state.images||[],selected=state.materialSourceFilter61||'all';
    if(selected!=='all')state.images=all.filter(row=>storageApi()?.sourceMatches(row,selected));
    try{finalDataset()}finally{state.images=all}
    const toolbar=document.querySelector('.data426-toolbar');
    if(toolbar&&!document.getElementById('materialSource61')){const enabled=storageApi()?.enabledStorageSources(state.storageSources61)||[];toolbar.insertAdjacentHTML('afterbegin',`<select id="materialSource61" class="select storage61-filter" onchange="state.materialSourceFilter61=this.value;renderDatasets424()"><option value="all">全部来源</option>${enabled.map(source=>`<option value="${source.id}" ${source.id===selected?'selected':''}>${esc(source.name)}</option>`).join('')}</select>`)}
    const visible=selected==='all'?all:all.filter(row=>storageApi()?.sourceMatches(row,selected));
    [...document.querySelectorAll('.data426-card')].forEach((card,index)=>{const row=visible[index],meta=card.querySelector('.data426-meta'),source=(state.storageSources61||[]).find(item=>item.id===(row?.storage_source_id||'default_local'));if(row&&meta&&!meta.querySelector('.storage61-badge'))meta.insertAdjacentHTML('beforeend',`<span class="storage61-badge">${esc(storageApi()?.storageSourceLabel(source)||row.storage_type||'本地')}</span>`) });
    if(!(state.storageSources61||[]).length&&!state.storageSourcesLoading61)loadStorageSources61().then(()=>state.page==='数据集'&&renderDatasets424()).catch(()=>{});
  };
  if(window.__storageOpenUpload61)window.openDataUpload426=window.__storageOpenUpload61;
  if(window.__storageDoUploadImages61)window.doUploadImages426=window.__storageDoUploadImages61;
  const finalRender=render;
  render=function(){if(state.page==='素材存储配置'){renderNav();renderTop();renderSummary();renderStorageSources61()}else finalRender();window.PostRenderNormalizationRuntime?.apply(document.getElementById('view'))};
})();
