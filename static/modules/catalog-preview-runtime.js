// Optional presentation owner. All requests use the original session/API owner.
export const PREVIEW_PAGE = '厂商芯片只读预览';
export function installCatalogPreview({enabled, navigation, getState, request, deadline, document = globalThis.document,
  load = async () => {
    if (!document.getElementById('catalog-preview-style')) {
      const style = document.createElement('link');style.id='catalog-preview-style';style.rel='stylesheet';style.href='/static/vue-catalog/catalog-preview.css';document.head.append(style);
    }
    return import('/static/vue-catalog/catalog-preview.js');
  }}) {
  let generation = 0, controller, unmount;
  function leave() { generation++; controller?.abort(); controller = null; unmount?.(); unmount = null; }
  async function render() {
    leave();
    const current = generation, project = getState().project?.id;
    const active = () => generation === current && getState().page === PREVIEW_PAGE && getState().project?.id === project;
    controller = new AbortController(); const signal = controller.signal;
    const host = document.createElement('div'); host.setAttribute('data-catalog-preview', '');
    host.textContent = '正在打开字典预览…'; document.getElementById('view').replaceChildren(host);
    try {
      const module = await load();
      if (!active()) return;
      const dispose = await module.mountCatalogPreview(host, {signal,
        async get(url, options = {}) {
          if (!/^\/api\/v39\/deploy\/catalog\/records(?:\?|\/(?:vendors|chips)\/[^/?#]+\?|$)/.test(url)
              || !new URL(url, 'http://localhost').searchParams.has('observe_only')
              || new URL(url, 'http://localhost').searchParams.get('observe_only') !== 'true') throw new Error('只读预览不允许该请求');
          if (!active() || signal.aborted) throw new DOMException('页面已离开', 'AbortError');
          const linked = new AbortController();
          const abort = () => linked.abort();
          signal.addEventListener('abort', abort, {once:true});
          options.signal?.addEventListener('abort', abort, {once:true});
          if (options.signal?.aborted) linked.abort();
          try { return await deadline(child => request(url, {method:'GET', signal:child}), {signal:linked.signal, timeoutMs:20000, label:'读取字典'}); }
          finally {signal.removeEventListener('abort',abort);options.signal?.removeEventListener('abort',abort);}
        },
        returnToManagement: () => globalThis.window.setPage('部署资源'),
      });
      if (!active()) dispose(); else unmount = dispose;
    } catch (error) {
      if (active() && !signal.aborted) {
        host.textContent = '字典预览未能打开。请确认已构建离线静态资源，或返回完整管理页面。';
        const back = document.createElement('button'); back.textContent = '返回完整管理';
        back.addEventListener('click', () => globalThis.window.setPage('部署资源'), {signal}); host.append(back);
      }
    }
  }
  const unregister = enabled ? navigation.registerPageOwner(PREVIEW_PAGE, render) : () => {};
  return {leave, destroy(){leave();unregister();}};
}
