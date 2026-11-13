/* 13C-04E: load the existing v40 component page on demand; no new business owners. */
export function installComponentScanRuntime({state,api,safe,toast,esc}={}) {
  if (!state || typeof api !== 'function' || typeof safe !== 'function'
      || typeof toast !== 'function' || typeof esc !== 'function')
    throw new Error('组件检测依赖未就绪');

  state.componentScan=state.componentScan||null;state.componentScanTimer=null;
  state.componentScanLoadedAt=Number(state.componentScanLoadedAt||0);
  const COMPONENT_SCAN_CACHE_KEY='cl_component_scan_v40_snapshot';
  const COMPONENT_SCAN_CACHE_TTL_MS=5*60*1000;
  const componentCacheShapeV40=s=>({
    id:s?.id||'',status:s?.status||'',stage:s?.stage||'',progress:Number(s?.progress||0),
    summary:s?.summary||{},components:Array.isArray(s?.components)?s.components:[],
    capabilities:Array.isArray(s?.capabilities)?s.capabilities:[],atlas:s?.atlas||null,
    created_at:s?.created_at||'',updated_at:s?.updated_at||'',
  });
  function restoreComponentScanCacheV40(){
    try{
      const cached=JSON.parse(localStorage.getItem(COMPONENT_SCAN_CACHE_KEY)||'null');
      if(!cached?.scan)return false;
      state.componentScan=componentCacheShapeV40(cached.scan);
      state.componentScanLoadedAt=Number(cached.ts||0);
      return true;
    }catch(_){return false}
  }
  function persistComponentScanCacheV40(){
    try{localStorage.setItem(COMPONENT_SCAN_CACHE_KEY,JSON.stringify({ts:Date.now(),scan:componentCacheShapeV40(state.componentScan)}))}catch(_){}
  }
  restoreComponentScanCacheV40();
  const compStatus=s=>`<span class="pill ${s==='ready'?'ok':s==='missing'?'err':'warn'}">${s==='ready'?'满足':s==='missing'?'缺失':'需确认'}</span>`;
  function compRow(c){return `<div class="component-row"><div class="component-state">${compStatus(c.status)}</div><div class="grow"><div class="item-title">${esc(c.name)}</div><div class="item-sub">${esc(c.version||'')}${c.path?` · ${esc(c.path)}`:''}</div>${c.detail?`<div class="component-detail">${esc(c.detail)}</div>`:''}${c.status!=='ready'&&c.fix?`<div class="component-fix">${esc(c.fix)}</div>`:''}</div></div>`}
  function capCard(c){return `<div class="capability-card ${c.status}"><div class="capability-head"><b>${esc(c.name)}</b>${compStatus(c.status)}</div><div class="item-sub">${esc(c.detail||(c.remote?'远程部署资源可用':'本机/已配置资源'))} · ${c.ready||0}/${c.total||0}</div></div>`}
  const COMPONENT_SCAN_POLL_KEY='component-scan-v40';
  function componentScanActive(s=state.componentScan){return ['queued','running'].includes(String(s?.status||'').toLowerCase())}
  function componentProgressValue(s=state.componentScan){return Math.max(0,Math.min(100,Number(s?.progress||0)))}
  function componentAtlasHtml(s){return s?.atlas?`<div class="atlas-check"><div><b>华为 Atlas / Ascend</b><span>${s.atlas.atc_ready?'OM 转换可用':'ATC 未就绪'}</span></div><div class="item-sub">${(s.atlas.detected_soc_versions||[]).length?'检测到 '+s.atlas.detected_soc_versions.join('、'):'未读取到本机 NPU；仍可在纯 CANN 转换服务器编译 OM，创建任务时填写目标 soc_version。'}</div></div>`:''}
  function componentBodyHtml(){const s=state.componentScan||{},sum=s.summary||{ready:0,warning:0,missing:0,total:0},progress=componentProgressValue(s),running=componentScanActive(s);return `<div class="component-summary"><div><span>满足</span><b data-component-summary="ready">${sum.ready||0}</b></div><div><span>需确认</span><b data-component-summary="warning">${sum.warning||0}</b></div><div><span>缺失</span><b data-component-summary="missing">${sum.missing||0}</b></div><div><span>总项</span><b data-component-summary="total">${sum.total||0}</b></div></div><div class="component-progress" data-component-progress ${running?'':'hidden'}><div class="progress-bar"><i data-component-progress-bar data-progress="${progress.toFixed(2)}" style="transform:scaleX(${(progress/100).toFixed(4)})"></i></div><div><b data-component-stage>${esc(s.stage||'检测中')}</b><span data-component-percent>${Math.round(progress)}%</span></div></div><div class="capability-grid" data-component-capabilities>${(s.capabilities||[]).map(capCard).join('')}</div><div class="component-grid" data-component-details><section class="component-group"><div class="component-group-title">组件明细</div>${(s.components||[]).map(compRow).join('')||'<div class="empty">尚未检测</div>'}</section></div><div data-component-atlas>${componentAtlasHtml(s)}</div>`}
  function renderCompBody(){const box=document.getElementById('componentBody');if(!box)return false;box.innerHTML=componentBodyHtml();return true}
  function patchCompProgress(){const box=document.getElementById('componentBody');if(!box)return false;if(!box.querySelector('[data-component-summary="total"]'))return renderCompBody();const s=state.componentScan||{},sum=s.summary||{ready:0,warning:0,missing:0,total:0},progress=componentProgressValue(s),running=componentScanActive(s);for(const key of ['ready','warning','missing','total']){const node=box.querySelector(`[data-component-summary="${key}"]`);if(node)node.textContent=String(sum[key]||0)}const progressBox=box.querySelector('[data-component-progress]'),bar=box.querySelector('[data-component-progress-bar]'),stage=box.querySelector('[data-component-stage]'),percent=box.querySelector('[data-component-percent]');if(progressBox)progressBox.hidden=!running;if(bar){bar.dataset.progress=progress.toFixed(2);bar.style.transform=`scaleX(${(progress/100).toFixed(4)})`}if(stage)stage.textContent=s.stage||'检测中';if(percent)percent.textContent=`${Math.round(progress)}%`;return true}
  function clearComponentScanPollV40(){window.PollRegistryRuntime?.clear?.(COMPONENT_SCAN_POLL_KEY);if(state.componentScanTimer!=null&&!window.PollRegistryRuntime?.clear){clearTimeout(state.componentScanTimer)}state.componentScanTimer=null}
  function armComponentScanPollV40(id){clearComponentScanPollV40();if(state.page!=='组件检测'||!id||!componentScanActive())return null;const callback=()=>window.pollComponentScanV40?.(id);state.componentScanTimer=window.PollRegistryRuntime?.startTimeout?.(COMPONENT_SCAN_POLL_KEY,'组件检测',callback,650)??setTimeout(callback,650);return state.componentScanTimer}
  window.renderComponentCheckV40=async()=>{
    const view=document.getElementById('view');if(!view)return false;
    view.innerHTML=`<section class="panel"><div class="panel-head"><div><div class="panel-title">组件检测</div><div class="subline">训练、导出、量化与芯片编译环境</div></div><button id="componentScanBtn" class="btn primary" onclick="startComponentScanV40()">${state.componentScan?'重新检测':'开始检测'}</button></div><div class="panel-body" id="componentBody">${componentBodyHtml()}</div></section>`;
    const age=Date.now()-Number(state.componentScanLoadedAt||0);
    const cacheFresh=!!state.componentScan&&!componentScanActive()&&state.componentScanLoadedAt>0&&age>=0&&age<COMPONENT_SCAN_CACHE_TTL_MS;
    if(cacheFresh){clearComponentScanPollV40();return true}
    const latest=await safe(api('/api/v40/system/components/latest'));if(state.page!=='组件检测')return false;
    if(latest){state.componentScan=latest;state.componentScanLoadedAt=Date.now();persistComponentScanCacheV40()}
    renderCompBody();if(componentScanActive())armComponentScanPollV40(state.componentScan?.id);else clearComponentScanPollV40();return true
  };
  window.startComponentScanV40=async()=>{const b=document.getElementById('componentScanBtn');if(b){b.disabled=true;b.innerHTML='<span class="tiny-spinner"></span>检测中'}try{const r=await api('/api/v40/system/components/scan',{method:'POST'});state.componentScan=r;state.componentScanLoadedAt=Date.now();persistComponentScanCacheV40();renderCompBody();armComponentScanPollV40(r.id)}catch(e){toast(e.message||e);if(b){b.disabled=false;b.textContent='开始检测'}}};
  window.pollComponentScanV40=async id=>{clearComponentScanPollV40();if(state.page!=='组件检测')return null;const r=await safe(api(`/api/v40/system/components/scan/${id}`));if(state.page!=='组件检测')return r;if(r){state.componentScan=r;state.componentScanLoadedAt=Date.now();persistComponentScanCacheV40();if(componentScanActive(r))patchCompProgress();else renderCompBody()}if(r&&componentScanActive(r)){armComponentScanPollV40(id)}else{clearComponentScanPollV40();const b=document.getElementById('componentScanBtn');if(b){b.disabled=false;b.textContent='重新检测'}if(r?.status==='done')toast('组件检测完成')}return r};
  return Object.freeze({render: (...args) => window.renderComponentCheckV40?.(...args)});
}
