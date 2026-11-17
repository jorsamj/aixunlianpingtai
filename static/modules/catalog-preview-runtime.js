import {readVueNavigation} from './ui-state.js?v=20261117p1z1';
// Optional presentation owner. All requests use the original session/API owner.
export const PREVIEW_PAGE = '厂商芯片只读预览';
export const MANAGEMENT_PAGE = '厂商芯片正式管理';
export const NODES_PAGE = '服务节点只读总览';
export const CONFIGURATION_PAGE = '统一配置中心';
export const WORKBENCH_PAGE = '统一工作台';
export const ASSETS_PAGE = '模型资产只读浏览';
export const MATERIALS_PAGE = '素材库正式浏览';
export const POOL_PAGE = '算法负样本池正式管理';
export const AI_TASKS_PAGE = 'AI标注任务正式浏览';
export const TASKS_PAGE = '训练任务只读中心';
export const REPORT_PAGE = '训练报告只读阅读';
export const HISTORY_PAGE = '版本转换只读历史';
export function installCatalogPreview({enabled, managementEnabled=false, nodesEnabled=false, configurationEnabled=false, workbenchEnabled=false, assetsEnabled=false, algorithmEnabled=false, tasksEnabled=false, reportsEnabled=false, materialsEnabled=false, importsEnabled=false, poolEnabled=false, aiTasksEnabled=false, createOperationId, navigation, getState, request, deadline, document = globalThis.document,
  load = async () => {
    let style=document.getElementById('catalog-preview-style');
    if(style?.dataset.failed){style.remove();style=null}
    const fresh=!style;
    if(fresh){style=document.createElement('link');style.id='catalog-preview-style';style.rel='stylesheet';style.href='/static/vue-catalog/catalog-preview.css?v=20261117p1z1'}
    const css=style.sheet?Promise.resolve():new Promise((resolve,reject)=>{
      const loaded=()=>{style.removeEventListener('error',failed);resolve()};
      const failed=()=>{style.removeEventListener('load',loaded);style.dataset.failed='true';reject(new Error('Vue 样式未能加载'))};
      style.addEventListener('load',loaded,{once:true});style.addEventListener('error',failed,{once:true});
    });
    if(fresh)document.head.append(style);
    const [,module]=await Promise.all([css,import('/static/vue-catalog/catalog-preview.js?v=20261117p1z1')]);
    return module;
  }}) {
  assetsEnabled=assetsEnabled||algorithmEnabled;
  nodesEnabled=nodesEnabled||configurationEnabled;
  let generation = 0, controller, unmount;
  const browseMemories=new Map();
  const memory=project=>{if(!browseMemories.has(project)){const saved=readVueNavigation(project);browseMemories.set(project,{...(saved?.selection?{selection:saved.selection}:{}),...(saved?.report?{report:saved.report}:{})})}return browseMemories.get(project)};
  function openHistory(algorithmId,versionId){
    if(!assetsEnabled||!algorithmId||!versionId)return;
    const project=getState().project?.id;if(!project)return;
    const state=memory(project),identity=JSON.stringify([algorithmId,versionId]);if(state.historyIdentity!==identity)state.history={page:1};state.historyIdentity=identity;
    state.selection={algorithmId,versionId};return globalThis.window.setPage(HISTORY_PAGE);
  }
  const packets=new Map();
  function pendingSlot(){
    // Catalog and revision are global. A project switch must not hide an unknown write.
    const key='cl_vue_catalog_pending_v1';
    if(!packets.has(key)){
      let value=null;try{const saved=JSON.parse(globalThis.sessionStorage?.getItem(key)||'null');if(saved&&typeof saved.operation_id==='string'&&['vendors','chips'].includes(saved.entity))value=saved}catch(_){}
      packets.set(key,{value,save(value){this.value=value;try{if(value)globalThis.sessionStorage?.setItem(key,JSON.stringify(value));else globalThis.sessionStorage?.removeItem(key)}catch(_){}}});
    }
    return packets.get(key);
  }
  function algorithmPending(project){
    const key='cl_vue_algorithm_pending_v1:'+project;
    if(!packets.has(key)){let value=null;try{value=JSON.parse(globalThis.sessionStorage?.getItem(key)||'null')}catch(_){}packets.set(key,{value,save(value){this.value=value;try{if(value)globalThis.sessionStorage?.setItem(key,JSON.stringify(value));else globalThis.sessionStorage?.removeItem(key)}catch(_){}}})}
    return packets.get(key);
  }
  function poolPending(){
    const key='cl_vue_pool_pending_v1';
    if(!packets.has(key)){
      let value=null;try{if(!globalThis.sessionStorage)throw new Error('操作恢复存储不可用');value=JSON.parse(globalThis.sessionStorage.getItem(key)||'null')}catch(_){value={invalid:true}}
      packets.set(key,{value,save(next){
        if(!globalThis.sessionStorage)throw new Error('操作恢复存储不可用，未提交');
        if(next)globalThis.sessionStorage.setItem(key,JSON.stringify(next));else globalThis.sessionStorage.removeItem(key);
        this.value=next;
      }});
    }
    return packets.get(key);
  }
  function leave() { generation++; controller?.abort(); controller = null; unmount?.(); unmount = null; }
  async function render(page=PREVIEW_PAGE) {
    leave();
    const current = generation, project = getState().project?.id;
    const active = () => generation === current && getState().page === page && getState().project?.id === project;
    controller = new AbortController(); const signal = controller.signal;
    const host = document.createElement('div'); host.setAttribute('data-catalog-preview', '');
    host.textContent = '正在打开 Vue 页面…'; document.getElementById('view').replaceChildren(host);
    try {
      const module = await load();
      if (!active()) return;
      const managed=page===MANAGEMENT_PAGE&&managementEnabled;
      const browsing=workbenchEnabled&&page===WORKBENCH_PAGE||assetsEnabled&&[ASSETS_PAGE,HISTORY_PAGE].includes(page)||tasksEnabled&&page===TASKS_PAGE||reportsEnabled&&page===REPORT_PAGE||materialsEnabled&&page===MATERIALS_PAGE||poolEnabled&&page===POOL_PAGE||aiTasksEnabled&&page===AI_TASKS_PAGE;
      const browse=memory(project),query=new URLSearchParams(globalThis.location?.search||'');
      if(browsing&&!browse.selection&&query.get('asset_algorithm')&&query.get('asset_version'))browse.selection={algorithmId:query.get('asset_algorithm'),versionId:query.get('asset_version')};
      const scopeError=browsing&&query.get('asset_project')&&query.get('asset_project')!==String(project)?'链接项目与当前项目身份不一致，请从当前项目重新选择。':'';
      const historySelection=browse.selection;
      const legacy=async selection=>{
        if(!active())return;const sameProject=project;
        await Promise.resolve(globalThis.window.setPage('算法列表'));
        if(getState().project?.id!==sameProject||getState().page!=='算法列表')return;
        if(selection?.algorithmId&&selection?.versionId)return globalThis.window.openVersionConvert428?.(selection.algorithmId,selection.versionId);
      };
      async function call(url,options={}){
          if (!active() || signal.aborted) throw new DOMException('页面已离开', 'AbortError');
          const linked = new AbortController();
          const abort = () => linked.abort();
          signal.addEventListener('abort', abort, {once:true});
          options.signal?.addEventListener('abort', abort, {once:true});
          if (options.signal?.aborted) linked.abort();
          try {
            const value=await deadline(child => request(url, {...options, signal:child}), {signal:linked.signal, timeoutMs:20000, label:'平台页面请求'});
            if(!active()){leave();throw new DOMException('项目或页面已变化','AbortError')}
            return value;
          }
          finally {signal.removeEventListener('abort',abort);options.signal?.removeEventListener('abort',abort);}
      }
      const configurationPages={nodes:NODES_PAGE,trainingResources:'训练资源',conversionResources:'部署资源',models:'模型配置',prompts:'模型配置',storage:'存储配置',platform:'平台对接',catalog:managementEnabled?MANAGEMENT_PAGE:'部署资源',algorithms:assetsEnabled?ASSETS_PAGE:'算法列表',legacyNodes:'服务节点'};
      const openConfigurationEntry=async id=>{
        if(!active()||!Object.hasOwn(configurationPages,id))return;
        const destination=configurationPages[id];await Promise.resolve(globalThis.window.setPage(destination));
        if(getState().project?.id!==project||getState().page!==destination)return;
        const section={prompts:'prompts',models:'models',trainingResources:'training',conversionResources:'resources',storage:'resources',legacyNodes:'nodes',...(destination==='部署资源'?{catalog:'catalog'}:{})}[id];
        if(section)return globalThis.window.PlatformCore?.navigation?.selectAdvancedSection?.(section);
      };
      const configurationEntries=[
        {id:'nodes',title:'服务节点与设备',description:'心跳、资源上报、能力与任务占用。',group:'计算资源',enabled:true},
        {id:'trainingResources',title:'训练资源与环境',description:'GPU、训练服务器与已有资源配置。',group:'计算资源',enabled:true},
        {id:'conversionResources',title:'转换资源与环境',description:'转换节点、SDK 与环境配置。检测由原页面显式操作。',group:'计算资源',enabled:true},
        {id:'models',title:'模型服务与 AI Provider',description:'视觉模型、服务连接、坐标协议与现有测试入口。',group:'模型与标注',enabled:true},
        {id:'prompts',title:'Prompt 与模板',description:'查看模型配置页中的提示词模板与版本。',group:'模型与标注',enabled:true},
        {id:'storage',title:'存储与模型归档',description:'OSS、S3、NAS 及模型和转换结果的存储配置。',group:'模型交付与存储',enabled:true},
        {id:'platform',title:'畅联云对接',description:'平台模式、主数据同步、映射与交付记录。',group:'模型交付与存储',enabled:true},
        {id:'catalog',title:'厂商与芯片',description:'正式字典、引用保护与历史绑定。',group:'基础字典',enabled:true},
        {id:'algorithms',title:'训练与转换参数',description:'从算法和版本进入，保持实际模型与任务上下文。',group:'计算资源',enabled:true},
      ];
      const workbenchPages={assets:ASSETS_PAGE,materials:MATERIALS_PAGE,imports:'素材上传与治理',ai:AI_TASKS_PAGE,training:TASKS_PAGE,nodes:NODES_PAGE,configuration:CONFIGURATION_PAGE};
      const context={signal,management:managed,
        ...(workbenchEnabled?{openWorkbench:()=>{if(active())return globalThis.window.setPage(WORKBENCH_PAGE)}}:{}),
        ...(page===WORKBENCH_PAGE&&workbenchEnabled?{entries:[
          {id:'assets',title:'算法与模型',description:'算法管理、模型版本、训练报告、转换与交付。'},
          {id:'materials',title:'素材管理',description:'素材筛选、历史使用、标注详情与负样本。'},
          {id:'imports',title:'上传与治理',description:'图片与 ZIP 上传、入库确认和清洗治理。'},
          {id:'ai',title:'AI 标注',description:'创建配置、任务进度、失败诊断与人工审核。'},
          {id:'training',title:'训练中心',description:'训练与准备任务、执行证据和报告。'},
          {id:'nodes',title:'资源管理',description:'节点、Worker 与上报资源，分别核对执行资格。'},
          {id:'configuration',title:'配置中心',description:'模型服务、存储、平台对接与正式字典。'},
        ],open:id=>{if(active()&&Object.hasOwn(workbenchPages,id))return globalThis.window.setPage(workbenchPages[id])},async legacyWorkbench(){
          if(!active())return;await Promise.resolve(globalThis.window.setPage('总览'));
          if(getState().project?.id!==project||getState().page!=='总览')return;
          const target=new URL(globalThis.window.location.href);target.searchParams.delete('vue_workbench');globalThis.window.location.assign(target.href);
        }}:{}),
        ...(configurationEnabled&&page!==WORKBENCH_PAGE?{projectId:String(project||''),entries:configurationEntries,open:openConfigurationEntry,back:()=>{if(active())return globalThis.window.setPage(NODES_PAGE)},openConfiguration:()=>{if(active())return globalThis.window.setPage(CONFIGURATION_PAGE)},openResource:kind=>openConfigurationEntry({training:'trainingResources',conversion:'conversionResources',models:'models',nodes:'legacyNodes'}[kind]),}:{}),
        async get(url, options = {}) {
          const parsed=new URL(url,'http://localhost');
          const records=/^\/api\/v39\/deploy\/catalog\/records(?:\?|\/(?:vendors|chips)\/[^/?#]+\?)/.test(url)&&parsed.searchParams.get('observe_only')==='true';
          const receipt=managed&&/^\/api\/v39\/deploy\/catalog\/operations\/[A-Za-z0-9_.-]+$/.test(url);
          const nodes=page===NODES_PAGE&&url==='/api/v63/service-nodes';
          const assetRoot=`/api/v12/projects/${encodeURIComponent(project||'')}/algorithms`;
          const local=/^\/api\/(?:v12|v42)\/projects\//.test(url);
          const assets=local&&[ASSETS_PAGE,POOL_PAGE].includes(page)&&parsed.searchParams.get('asset_view')==='true'&&((parsed.pathname===assetRoot&&parsed.searchParams.get('summary_only')==='true')||(parsed.pathname.startsWith(assetRoot+'/')&&parsed.pathname.slice(assetRoot.length+1).split('/').length===1));
          const taskRoot=`/api/v62/projects/${encodeURIComponent(project||'')}/tasks`;
          const tasks=[TASKS_PAGE,WORKBENCH_PAGE].includes(page)&&url.startsWith('/api/v62/')&&parsed.searchParams.get('reader_view')==='true'&&(parsed.pathname===taskRoot||(parsed.pathname.startsWith(taskRoot+'/')&&parsed.pathname.slice(taskRoot.length+1).split('/').length===1));
          const report=page===REPORT_PAGE&&url.startsWith('/api/v44/')&&parsed.searchParams.get('reader_view')==='true'&&parsed.pathname===`/api/v44/projects/${encodeURIComponent(project||'')}/jobs/${encodeURIComponent(browse.report?.jobId||'')}/report`;
          const reportAlgorithm=String(browse.report?.algorithmId||''),reportVersion=String(browse.report?.versionId||'');
          const evaluationRoot=`${assetRoot}/${encodeURIComponent(reportAlgorithm)}/versions/${encodeURIComponent(reportVersion)}/evaluation`;
          const evaluation=page===REPORT_PAGE&&reportAlgorithm&&reportVersion&&url.startsWith('/api/v12/')&&parsed.searchParams.get('reader_view')==='true'&&([evaluationRoot+'/report',evaluationRoot+'/samples'].includes(parsed.pathname)||(parsed.pathname.startsWith(evaluationRoot+'/compare/')&&/^[-A-Za-z0-9_]{1,128}$/.test(parsed.pathname.slice((evaluationRoot+'/compare/').length))));
          const reportVersions=page===REPORT_PAGE&&reportAlgorithm&&url.startsWith('/api/v12/')&&parsed.searchParams.get('asset_view')==='true'&&parsed.pathname===assetRoot+'/'+encodeURIComponent(reportAlgorithm);
          const materialRoot=`/api/v61/projects/${encodeURIComponent(project||'')}/materials`,annotationRoot=`/api/projects/${encodeURIComponent(project||'')}/annotations/`;
          const materialReads=page===MATERIALS_PAGE&&parsed.searchParams.get('reader_view')==='true'&&((url.startsWith('/api/v61/')&&parsed.pathname===materialRoot)||(url.startsWith('/api/projects/')&&parsed.pathname.startsWith(annotationRoot)&&parsed.pathname.slice(annotationRoot.length).split('/').length===1));
          const aiRoot=`/api/v60/projects/${encodeURIComponent(project||'')}/annotation-tasks`;
          const aiRead=[AI_TASKS_PAGE,WORKBENCH_PAGE].includes(page)&&url.startsWith('/api/v60/')&&parsed.searchParams.get('reader_view')==='true'&&(parsed.pathname===aiRoot||parsed.pathname.startsWith(aiRoot+'/')&&parsed.pathname.slice(aiRoot.length+1).split('/').length===1||parsed.pathname.startsWith(aiRoot+'/')&&parsed.pathname.slice(aiRoot.length+1).split('/').length===2&&parsed.pathname.endsWith('/candidates')&&parsed.searchParams.get('filter')==='failed');
          const poolRoot=`/api/v61/projects/${encodeURIComponent(project||'')}/negative-pool`;
          const poolRead=page===POOL_PAGE&&url.startsWith('/api/v61/')&&((parsed.pathname===poolRoot&&parsed.searchParams.get('reader_view')==='true')||parsed.pathname===poolRoot+'/categories'||new RegExp('^'+poolRoot+'/operations/[A-Za-z0-9_-]{1,128}$').test(parsed.pathname));
          const history=local&&page===HISTORY_PAGE&&parsed.searchParams.get('asset_view')==='true'&&parsed.pathname===`/api/v42/projects/${encodeURIComponent(project||'')}/algorithms/${encodeURIComponent(historySelection?.algorithmId||'')}/versions/${encodeURIComponent(historySelection?.versionId||'')}/deployments`;
          if(page===WORKBENCH_PAGE&&(!(parsed.pathname===taskRoot||parsed.pathname===aiRoot)||Number(parsed.searchParams.get('limit'))!==5))throw new Error('工作台只允许有界近期任务读取');
          if(browsing&&!project)throw new Error('当前项目尚未就绪');
          if(browsing&&scopeError)throw new Error(scopeError);
          if(!(page!==NODES_PAGE&&!browsing&&records||receipt||nodes||browsing&&(assets||history||tasks||report||evaluation||reportVersions||materialReads||poolRead||aiRead)))throw new Error('只读或管理页面不允许该请求');
          return call(url,{...options,method:'GET'});
        },
        ...(managed?{post(url,body){
          if(!(/^\/api\/v39\/deploy\/catalog\/operations$/.test(url)||/^\/api\/v39\/deploy\/catalog\/chips\/[^/?#]+\/detect$/.test(url)))throw new Error('管理页面不允许该写入');
          return call(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        },createOperationId,pending:pendingSlot(),invalidate:()=>globalThis.window.invalidateVersionConversionResources428?.()}:{}),
        ...(algorithmEnabled&&page===ASSETS_PAGE?{algorithmManagement:true,algorithmPending:algorithmPending(project),writeAlgorithm(method,id,body){
          if(typeof id!=='string'||/[\\/]/.test(id)||['.','..'].includes(id))throw new Error('算法管理仅接受稳定算法ID');
          if(!project||scopeError||!['POST','PUT'].includes(method)||method==='PUT'&&!id||method==='POST'&&id||Object.keys(body).some(key=>!['name','remark','industry','algorithm_type'].includes(key)))throw new Error('算法管理不允许该写入');
          const root=`/api/v12/projects/${encodeURIComponent(project)}/algorithms`;
          return call(root+(id?'/'+encodeURIComponent(id):'')+'?asset_view=true',{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        }}:{}),
        ...(aiTasksEnabled?{openAiReview:async(id)=>{if(!active()||!/^[-A-Za-z0-9_]{1,128}$/.test(String(id)))return;await Promise.resolve(globalThis.window.setPage('自动标注及清洗'));if(getState().project?.id===project&&getState().page==='自动标注及清洗')return globalThis.window.reviewAiLabel427?.(id)},legacyAi:async(action,id)=>{if(!active())return;await Promise.resolve(globalThis.window.setPage('自动标注及清洗'));if(getState().project?.id!==project||getState().page!=='自动标注及清洗')return;if(action==='create')return globalThis.window.createAiLabel427?.();if(id)return globalThis.window.showAiTask60?.(id)}}:{}),
        ...(poolEnabled?{openNegativePool:()=>{if(active())return globalThis.window.setPage(POOL_PAGE)}}:{}),
        ...(poolEnabled&&page===POOL_PAGE?{poolPending:poolPending(),createOperationId,poolWrite(packet){
          if(packet.project_id!==String(project)||!packet.algorithm_id||!['add','remove'].includes(packet.action)||!Array.isArray(packet.image_ids)||packet.image_ids.length<1||packet.image_ids.length>200||!/^[-A-Za-z0-9_]{1,128}$/.test(packet.operation_id))throw new Error('负样本成员操作身份无效');
          const {project_id,...body}=packet;return call(`/api/v61/projects/${encodeURIComponent(project)}/negative-pool/members`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        },async legacyPool(){if(!active())return;await Promise.resolve(globalThis.window.setPage('数据集'));if(getState().project?.id===project&&getState().page==='数据集')return globalThis.window.NegativePoolRuntime?.open?.()}}:{}),
        ...(importsEnabled?{openImports:()=>{if(active())return globalThis.window.setPage('素材上传与治理')}}:{}),
        ...(materialsEnabled?{openMaterials:()=>{if(active())return globalThis.window.setPage(MATERIALS_PAGE)},async legacyMaterials(action='manage',id){
          if(!active())return;await Promise.resolve(globalThis.window.setPage('数据集'));
          if(getState().project?.id!==project||getState().page!=='数据集')return;
          if(action==='upload')return globalThis.window.openDataUpload426?.();
          if(action==='annotate'&&id)return globalThis.window.openAnnotation?.(id);
        },history(id,page=1,childSignal){
          if(!project||typeof id!=='string'||/[\\/]/.test(id)||!Number.isInteger(page)||page<1)throw new Error('素材历史请求身份无效');
          return call(`/api/v62/projects/${encodeURIComponent(project)}/training-materials/history`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_id:id,algorithm_asset_id:browse.selection?.algorithmId||'',page,page_size:20}),signal:childSignal});
        }}:{}),
        ...(tasksEnabled?{openTasks:(query)=>{if(!active())return;if(query)browse.tasks={filters:{query,status:'',kind:''},cursors:[''],index:0};return globalThis.window.setPage(TASKS_PAGE)}}:{}),
        ...(tasksEnabled?{async legacyTask(id,action){if(!active()||!/^[-A-Za-z0-9_]{1,128}$/.test(String(id))||!['detail','log'].includes(action))return;await Promise.resolve(globalThis.window.setPage('训练任务'));if(getState().project?.id!==project||getState().page!=='训练任务')return;return action==='log'?globalThis.window.showTrainLog423?.(id):globalThis.window.openTrainingRecoveryDetail?.(id)}}:{}),
        ...(reportsEnabled?{openReport(selection){if(!active())return;browse.report={...selection};return globalThis.window.setPage(REPORT_PAGE)},async legacyReport(selection){
          if(!active())return;const destination=selection.returnPage==='tasks'?'训练任务':'算法列表';await Promise.resolve(globalThis.window.setPage(destination));
          if(getState().project?.id!==project||getState().page!==destination)return;
          if(selection.algorithmId&&selection.versionId)return globalThis.window.openVersionReport429?.(selection.algorithmId,selection.versionId);
          return globalThis.window.openJobReport429?.(selection.jobId);
        }}:{}),
        ...(browsing?{projectId:String(project||''),memory:browse,scopeError,openHistory(selection){
          if(!active())return;const identity=JSON.stringify([selection.algorithmId,selection.versionId]);if(browse.historyIdentity!==identity)browse.history={page:1};browse.historyIdentity=identity;browse.selection={...selection};return globalThis.window.setPage(HISTORY_PAGE);
        },async openDelivery(selection){if(!active()||!selection?.algorithmId||!selection?.versionId)return;await Promise.resolve(globalThis.window.setPage('算法列表'));if(getState().project?.id===project&&getState().page==='算法列表')return globalThis.window.ExternalAlgorithmPublishRuntime?.publishVersion?.(selection.algorithmId,selection.versionId)},async openConversionLog(id){if(!active()||!/^[-A-Za-z0-9_.]{1,128}$/.test(String(id)))return;await Promise.resolve(globalThis.window.setPage('算法列表'));if(getState().project?.id===project&&getState().page==='算法列表')return globalThis.window.openDeployLog?.(id)},async openConversionCreate(selection){if(!active()||!selection?.algorithmId||!selection?.versionId)return;await Promise.resolve(globalThis.window.setPage('算法列表'));if(getState().project?.id===project&&getState().page==='算法列表')return globalThis.window.openNewConvert428?.(selection.algorithmId,selection.versionId)},returnToAssets:()=>globalThis.window.setPage(ASSETS_PAGE),openLegacy:legacy}:{}),
        returnToManagement: () => globalThis.window.setPage(browsing?(page===AI_TASKS_PAGE?'自动标注及清洗':[MATERIALS_PAGE,POOL_PAGE].includes(page)?'数据集':page===TASKS_PAGE?'训练任务':'算法列表'):page===NODES_PAGE?'服务节点':'部署资源'),
      };
      const mount=page===WORKBENCH_PAGE?module.mountProductWorkbench:page===CONFIGURATION_PAGE?module.mountConfigurationCenter:page===AI_TASKS_PAGE?module.mountAiAnnotationTasks:page===POOL_PAGE?module.mountNegativePool:page===MATERIALS_PAGE?module.mountMaterialLibrary:page===TASKS_PAGE?module.mountTrainingTasks:page===REPORT_PAGE?module.mountTrainingReport:page===NODES_PAGE?module.mountServiceNodes:page===ASSETS_PAGE?module.mountModelAssets:page===HISTORY_PAGE?module.mountConversionHistory:module.mountCatalogPreview;
      const dispose = await mount(host,context);
      if (!active()) dispose(); else unmount = dispose;
    } catch (error) {
      if (active() && !signal.aborted) {
        host.textContent = 'Vue 页面未能打开。请确认已构建离线静态资源，或返回完整管理页面。';
        const back = document.createElement('button'); back.textContent = '返回完整管理';
        back.addEventListener('click', () => globalThis.window.setPage(page===WORKBENCH_PAGE?'总览':page===AI_TASKS_PAGE?'自动标注及清洗':[MATERIALS_PAGE,POOL_PAGE].includes(page)?'数据集':page===TASKS_PAGE?'训练任务':[ASSETS_PAGE,HISTORY_PAGE,REPORT_PAGE].includes(page)?'算法列表':page===NODES_PAGE?'服务节点':'部署资源'), {signal}); host.append(back);
      }
    }
  }
  const unregister=[];
  for(const [allowed,page] of [[workbenchEnabled,WORKBENCH_PAGE],[configurationEnabled,CONFIGURATION_PAGE],[enabled,PREVIEW_PAGE],[managementEnabled,MANAGEMENT_PAGE],[nodesEnabled,NODES_PAGE],[assetsEnabled,ASSETS_PAGE],[assetsEnabled,HISTORY_PAGE],[tasksEnabled,TASKS_PAGE],[reportsEnabled,REPORT_PAGE],[materialsEnabled,MATERIALS_PAGE],[poolEnabled,POOL_PAGE],[aiTasksEnabled,AI_TASKS_PAGE]])if(allowed)unregister.push(navigation.registerPageOwner(page,()=>render(page)));
  return {leave,openHistory,navigationContext(){const project=getState().project?.id,saved=browseMemories.get(project);return project&&saved?{project_id:project,selection:saved.selection,report:saved.report}:null},aiTasksEnabled,openAiTasks(){if(aiTasksEnabled)return globalThis.window.setPage(AI_TASKS_PAGE)},async mountTrainingPicker(host,context){const module=await load();return module.mountTrainingMaterialPicker(host,context)},async mountAiAnnotationCreate(host,context){if(context.signal.aborted)return ()=>{};const module=await load();if(context.signal.aborted)return ()=>{};return module.mountAiAnnotationCreate(host,context)},async mountMaterialImportGovernance(host,context){if(context.signal.aborted)return ()=>{};const module=await load();if(context.signal.aborted)return ()=>{};return module.mountMaterialImportGovernance(host,context)},async mountModelDelivery(host,context){if(context.signal.aborted)return ()=>{};const module=await load();if(context.signal.aborted)return ()=>{};return module.mountModelDelivery(host,context)},async mountConversionCreate(host,context){const module=await load();return module.mountConversionCreate(host,context)},async mountTrainingCreate(host,context){const module=await load();return module.mountTrainingCreate(host,context)},async mountAiReview(host,context){const module=await load();return module.mountAiReviewWorkbench(host,context)},destroy(){leave();unregister.forEach(dispose=>dispose());}};
}
