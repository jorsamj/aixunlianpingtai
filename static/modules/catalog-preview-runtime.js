// Optional presentation owner. All requests use the original session/API owner.
export const PREVIEW_PAGE = '厂商芯片只读预览';
export const MANAGEMENT_PAGE = '厂商芯片正式管理';
export const NODES_PAGE = '服务节点只读总览';
export const ASSETS_PAGE = '模型资产只读浏览';
export const HISTORY_PAGE = '版本转换只读历史';
export function installCatalogPreview({enabled, managementEnabled=false, nodesEnabled=false, assetsEnabled=false, createOperationId, navigation, getState, request, deadline, document = globalThis.document,
  load = async () => {
    let style=document.getElementById('catalog-preview-style');
    if(style?.dataset.failed){style.remove();style=null}
    const fresh=!style;
    if(fresh){style=document.createElement('link');style.id='catalog-preview-style';style.rel='stylesheet';style.href='/static/vue-catalog/catalog-preview.css?v=20261117p1g'}
    const css=style.sheet?Promise.resolve():new Promise((resolve,reject)=>{
      const loaded=()=>{style.removeEventListener('error',failed);resolve()};
      const failed=()=>{style.removeEventListener('load',loaded);style.dataset.failed='true';reject(new Error('Vue 样式未能加载'))};
      style.addEventListener('load',loaded,{once:true});style.addEventListener('error',failed,{once:true});
    });
    if(fresh)document.head.append(style);
    const [,module]=await Promise.all([css,import('/static/vue-catalog/catalog-preview.js?v=20261117p1g')]);
    return module;
  }}) {
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
      const browsing=assetsEnabled&&[ASSETS_PAGE,HISTORY_PAGE].includes(page);
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
          const history=local&&page===HISTORY_PAGE&&parsed.searchParams.get('asset_view')==='true'&&parsed.pathname===`/api/v42/projects/${encodeURIComponent(project||'')}/algorithms/${encodeURIComponent(historySelection?.algorithmId||'')}/versions/${encodeURIComponent(historySelection?.versionId||'')}/deployments`;
          if(browsing&&!project)throw new Error('当前项目尚未就绪');
          if(browsing&&scopeError)throw new Error(scopeError);
          if(!(page!==NODES_PAGE&&!browsing&&records||receipt||nodes||browsing&&(assets||history)))throw new Error('只读或管理页面不允许该请求');
          return call(url,{...options,method:'GET'});
        },
        ...(managed?{post(url,body){
          if(!(/^\/api\/v39\/deploy\/catalog\/operations$/.test(url)||/^\/api\/v39\/deploy\/catalog\/chips\/[^/?#]+\/detect$/.test(url)))throw new Error('管理页面不允许该写入');
          return call(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        },createOperationId,pending:pendingSlot(),invalidate:()=>globalThis.window.invalidateVersionConversionResources428?.()}:{}),
        ...(browsing?{projectId:String(project||''),memory:browse,scopeError,openHistory(selection){
          if(!active())return;const identity=JSON.stringify([selection.algorithmId,selection.versionId]);if(browse.historyIdentity!==identity)browse.history={page:1};browse.historyIdentity=identity;browse.selection={...selection};return globalThis.window.setPage(HISTORY_PAGE);
        },returnToAssets:()=>globalThis.window.setPage(ASSETS_PAGE),openLegacy:legacy}:{}),
        returnToManagement: () => globalThis.window.setPage(browsing?'算法列表':page===NODES_PAGE?'服务节点':'部署资源'),
      };
      const mount=page===NODES_PAGE?module.mountServiceNodes:page===ASSETS_PAGE?module.mountModelAssets:page===HISTORY_PAGE?module.mountConversionHistory:module.mountCatalogPreview;
      const dispose = await mount(host,context);
      if (!active()) dispose(); else unmount = dispose;
    } catch (error) {
      if (active() && !signal.aborted) {
        host.textContent = 'Vue 页面未能打开。请确认已构建离线静态资源，或返回完整管理页面。';
        const back = document.createElement('button'); back.textContent = '返回完整管理';
        back.addEventListener('click', () => globalThis.window.setPage([ASSETS_PAGE,HISTORY_PAGE].includes(page)?'算法列表':page===NODES_PAGE?'服务节点':'部署资源'), {signal}); host.append(back);
      }
    }
  }
  const unregister=[];
  for(const [allowed,page] of [[enabled,PREVIEW_PAGE],[managementEnabled,MANAGEMENT_PAGE],[nodesEnabled,NODES_PAGE],[assetsEnabled,ASSETS_PAGE],[assetsEnabled,HISTORY_PAGE]])if(allowed)unregister.push(navigation.registerPageOwner(page,()=>render(page)));
  return {leave,openHistory,destroy(){leave();unregister.forEach(dispose=>dispose());}};
}
