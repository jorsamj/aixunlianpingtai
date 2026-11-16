// Optional presentation owner. All requests use the original session/API owner.
export const PREVIEW_PAGE = '厂商芯片只读预览';
export const MANAGEMENT_PAGE = '厂商芯片正式管理';
export const NODES_PAGE = '服务节点只读总览';
export function installCatalogPreview({enabled, managementEnabled=false, nodesEnabled=false, createOperationId, navigation, getState, request, deadline, document = globalThis.document,
  load = async () => {
    let style=document.getElementById('catalog-preview-style');
    if(style?.dataset.failed){style.remove();style=null}
    const fresh=!style;
    if(fresh){style=document.createElement('link');style.id='catalog-preview-style';style.rel='stylesheet';style.href='/static/vue-catalog/catalog-preview.css?v=20261116p1d'}
    const css=style.sheet?Promise.resolve():new Promise((resolve,reject)=>{
      const loaded=()=>{style.removeEventListener('error',failed);resolve()};
      const failed=()=>{style.removeEventListener('load',loaded);style.dataset.failed='true';reject(new Error('Vue 样式未能加载'))};
      style.addEventListener('load',loaded,{once:true});style.addEventListener('error',failed,{once:true});
    });
    if(fresh)document.head.append(style);
    const [,module]=await Promise.all([css,import('/static/vue-catalog/catalog-preview.js?v=20261116p1d')]);
    return module;
  }}) {
  let generation = 0, controller, unmount;
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
    host.textContent = '正在打开字典预览…'; document.getElementById('view').replaceChildren(host);
    try {
      const module = await load();
      if (!active()) return;
      const managed=page===MANAGEMENT_PAGE&&managementEnabled;
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
          if(!(page!==NODES_PAGE&&records||receipt||nodes))throw new Error('只读或管理页面不允许该请求');
          return call(url,{...options,method:'GET'});
        },
        ...(managed?{post(url,body){
          if(!(/^\/api\/v39\/deploy\/catalog\/operations$/.test(url)||/^\/api\/v39\/deploy\/catalog\/chips\/[^/?#]+\/detect$/.test(url)))throw new Error('管理页面不允许该写入');
          return call(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        },createOperationId,pending:pendingSlot(),invalidate:()=>globalThis.window.invalidateVersionConversionResources428?.()}:{}),
        returnToManagement: () => globalThis.window.setPage(page===NODES_PAGE?'服务节点':'部署资源'),
      };
      const dispose = await (page===NODES_PAGE?module.mountServiceNodes:module.mountCatalogPreview)(host,context);
      if (!active()) dispose(); else unmount = dispose;
    } catch (error) {
      if (active() && !signal.aborted) {
        host.textContent = 'Vue 页面未能打开。请确认已构建离线静态资源，或返回完整管理页面。';
        const back = document.createElement('button'); back.textContent = '返回完整管理';
        back.addEventListener('click', () => globalThis.window.setPage(page===NODES_PAGE?'服务节点':'部署资源'), {signal}); host.append(back);
      }
    }
  }
  const unregister=[];
  for(const [allowed,page] of [[enabled,PREVIEW_PAGE],[managementEnabled,MANAGEMENT_PAGE],[nodesEnabled,NODES_PAGE]])if(allowed)unregister.push(navigation.registerPageOwner(page,()=>render(page)));
  return {leave, destroy(){leave();unregister.forEach(dispose=>dispose());}};
}
