// Optional presentation owner. All requests use the original session/API owner.
export const PREVIEW_PAGE = '厂商芯片只读预览';
export const MANAGEMENT_PAGE = '厂商芯片正式管理';
export const NODES_PAGE = '服务节点只读总览';
export const ASSETS_PAGE = '模型资产只读浏览';
export const TASKS_PAGE = '训练任务只读中心';
export const REPORT_PAGE = '训练报告只读阅读';
export const HISTORY_PAGE = '版本转换只读历史';
export function installCatalogPreview({enabled, managementEnabled=false, nodesEnabled=false, assetsEnabled=false, algorithmEnabled=false, tasksEnabled=false, reportsEnabled=false, createOperationId, navigation, getState, request, deadline, document = globalThis.document,
  load = async () => {
    let style=document.getElementById('catalog-preview-style');
    if(style?.dataset.failed){style.remove();style=null}
    const fresh=!style;
    if(fresh){style=document.createElement('link');style.id='catalog-preview-style';style.rel='stylesheet';style.href='/static/vue-catalog/catalog-preview.css?v=20261117p1hj'}
    const css=style.sheet?Promise.resolve():new Promise((resolve,reject)=>{
      const loaded=()=>{style.removeEventListener('error',failed);resolve()};
      const failed=()=>{style.removeEventListener('load',loaded);style.dataset.failed='true';reject(new Error('Vue 样式未能加载'))};
      style.addEventListener('load',loaded,{once:true});style.addEventListener('error',failed,{once:true});
    });
    if(fresh)document.head.append(style);
    const [,module]=await Promise.all([css,import('/static/vue-catalog/catalog-preview.js?v=20261117p1hj')]);
    return module;
  }}) {
  assetsEnabled=assetsEnabled||algorithmEnabled;
  let generation = 0, controller, unmount;
  const browseMemories=new Map();
  const memory=project=>{if(!browseMemories.has(project))browseMemories.set(project,{});return browseMemories.get(project)};
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
      const browsing=assetsEnabled&&[ASSETS_PAGE,HISTORY_PAGE].includes(page)||tasksEnabled&&page===TASKS_PAGE||reportsEnabled&&page===REPORT_PAGE;
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
      const context={signal,management:managed,
        async get(url, options = {}) {
          const parsed=new URL(url,'http://localhost');
          const records=/^\/api\/v39\/deploy\/catalog\/records(?:\?|\/(?:vendors|chips)\/[^/?#]+\?)/.test(url)&&parsed.searchParams.get('observe_only')==='true';
          const receipt=managed&&/^\/api\/v39\/deploy\/catalog\/operations\/[A-Za-z0-9_.-]+$/.test(url);
          const nodes=page===NODES_PAGE&&url==='/api/v63/service-nodes';
          const assetRoot=`/api/v12/projects/${encodeURIComponent(project||'')}/algorithms`;
          const local=/^\/api\/(?:v12|v42)\/projects\//.test(url);
          const assets=local&&page===ASSETS_PAGE&&parsed.searchParams.get('asset_view')==='true'&&((parsed.pathname===assetRoot&&parsed.searchParams.get('summary_only')==='true')||(parsed.pathname.startsWith(assetRoot+'/')&&parsed.pathname.slice(assetRoot.length+1).split('/').length===1));
          const taskRoot=`/api/v62/projects/${encodeURIComponent(project||'')}/tasks`;
          const tasks=page===TASKS_PAGE&&url.startsWith('/api/v62/')&&parsed.searchParams.get('reader_view')==='true'&&(parsed.pathname===taskRoot||(parsed.pathname.startsWith(taskRoot+'/')&&parsed.pathname.slice(taskRoot.length+1).split('/').length===1));
          const report=page===REPORT_PAGE&&url.startsWith('/api/v44/')&&parsed.searchParams.get('reader_view')==='true'&&parsed.pathname===`/api/v44/projects/${encodeURIComponent(project||'')}/jobs/${encodeURIComponent(browse.report?.jobId||'')}/report`;
          const history=local&&page===HISTORY_PAGE&&parsed.searchParams.get('asset_view')==='true'&&parsed.pathname===`/api/v42/projects/${encodeURIComponent(project||'')}/algorithms/${encodeURIComponent(historySelection?.algorithmId||'')}/versions/${encodeURIComponent(historySelection?.versionId||'')}/deployments`;
          if(browsing&&!project)throw new Error('当前项目尚未就绪');
          if(browsing&&scopeError)throw new Error(scopeError);
          if(!(page!==NODES_PAGE&&!browsing&&records||receipt||nodes||browsing&&(assets||history||tasks||report)))throw new Error('只读或管理页面不允许该请求');
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
        ...(tasksEnabled?{openTasks:(query)=>{if(!active())return;if(query)browse.tasks={filters:{query,status:'',kind:''},cursors:[''],index:0};return globalThis.window.setPage(TASKS_PAGE)}}:{}),
        ...(reportsEnabled?{openReport(selection){if(!active())return;browse.report={...selection};return globalThis.window.setPage(REPORT_PAGE)},async legacyReport(selection){
          if(!active())return;await Promise.resolve(globalThis.window.setPage(selection.returnPage==='tasks'?'训练任务':'算法列表'));
          if(getState().project?.id!==project)return;
          if(selection.algorithmId&&selection.versionId)return globalThis.window.openVersionReport429?.(selection.algorithmId,selection.versionId);
          return globalThis.window.openJobReport429?.(selection.jobId);
        }}:{}),
        ...(browsing?{projectId:String(project||''),memory:browse,scopeError,openHistory(selection){
          if(!active())return;const identity=JSON.stringify([selection.algorithmId,selection.versionId]);if(browse.historyIdentity!==identity)browse.history={page:1};browse.historyIdentity=identity;browse.selection={...selection};return globalThis.window.setPage(HISTORY_PAGE);
        },returnToAssets:()=>globalThis.window.setPage(ASSETS_PAGE),openLegacy:legacy}:{}),
        returnToManagement: () => globalThis.window.setPage(browsing?(page===TASKS_PAGE?'训练任务':'算法列表'):page===NODES_PAGE?'服务节点':'部署资源'),
      };
      const mount=page===TASKS_PAGE?module.mountTrainingTasks:page===REPORT_PAGE?module.mountTrainingReport:page===NODES_PAGE?module.mountServiceNodes:page===ASSETS_PAGE?module.mountModelAssets:page===HISTORY_PAGE?module.mountConversionHistory:module.mountCatalogPreview;
      const dispose = await mount(host,context);
      if (!active()) dispose(); else unmount = dispose;
    } catch (error) {
      if (active() && !signal.aborted) {
        host.textContent = 'Vue 页面未能打开。请确认已构建离线静态资源，或返回完整管理页面。';
        const back = document.createElement('button'); back.textContent = '返回完整管理';
        back.addEventListener('click', () => globalThis.window.setPage(page===TASKS_PAGE?'训练任务':[ASSETS_PAGE,HISTORY_PAGE,REPORT_PAGE].includes(page)?'算法列表':page===NODES_PAGE?'服务节点':'部署资源'), {signal}); host.append(back);
      }
    }
  }
  const unregister=[];
  for(const [allowed,page] of [[enabled,PREVIEW_PAGE],[managementEnabled,MANAGEMENT_PAGE],[nodesEnabled,NODES_PAGE],[assetsEnabled,ASSETS_PAGE],[assetsEnabled,HISTORY_PAGE],[tasksEnabled,TASKS_PAGE],[reportsEnabled,REPORT_PAGE]])if(allowed)unregister.push(navigation.registerPageOwner(page,()=>render(page)));
  return {leave,openHistory,destroy(){leave();unregister.forEach(dispose=>dispose());}};
}
