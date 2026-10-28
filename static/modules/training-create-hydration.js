import {withRequestDeadline} from './api.js?v=20261021s';

export function trainingOptionsHydrated(targets = []) {
  return (targets || []).some(target => (
    target?.status === 'ready'
    && Array.isArray(target.algorithms)
    && target.algorithms.length > 0
    && Array.isArray(target.base_models)
  ));
}

export function trainingCreationInputsReady(state = {}) {
  return trainingOptionsHydrated(state.targets);
}

export function installTrainingCreateHydrationRuntime({
  getState,
  projectId,
  request = async (url, options) => {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  },
  requestTimeoutMs = 30000,
  preflight,
  preflightFresh,
  openTrainingForm,
  openShell,
  isShellCurrent,
  closeShell,
  notify = () => {},
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingCreateHydrationInstalled) return window.TrainingCreateHydrationRuntime || null;

  const openForm = openTrainingForm || window.openTrainingCreateCanonical429;
  if (typeof openForm !== 'function') return null;

  let optionsInflight = null;
  let recommendationInflight = null;
  let optionsController = null;
  let recommendationController = null;
  let commonLoadedAt = trainingOptionsHydrated(getState?.()?.targets) ? Date.now() : 0;
  let commonProjectId = String(projectId?.()||'');
  let recommendationLoadedAt = 0;
  let activeOpening = null;
  let openEpoch = 0;
  let destroyed = false;
  const COMMON_INPUT_TTL_MS = 5 * 60 * 1000;
  const prewarmInflight = new Map();

  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const clockNow=()=>globalThis.performance?.now?.()??Date.now();
  const jsonSize=value=>typeof TextEncoder==='undefined'?null:new TextEncoder().encode(JSON.stringify(value)).length;
  const stageLabels={resources:'训练资源',recommendation:'推荐配置',preflight:'外部算法状态'};
  const liveOpening=()=>activeOpening && !destroyed && activeOpening.project===String(projectId?.()||'') && activeOpening.root?.isConnected && activeOpening.root===document.querySelector('.train429-create');
  function paintStages(){
    if(!liveOpening())return;
    const stages=getState?.()?.trainingCreationLoading||{};
    let box=activeOpening.root.querySelector('[data-training-input-status]');
    if(!box){box=document.createElement('div');box.dataset.trainingInputStatus='1';activeOpening.root.prepend(box);}
    box.setAttribute('aria-live','polite');
    const html=Object.entries(stageLabels).map(([key,title])=>{
      const value=stages[key]||{},status=value.status||'idle';
      const label=({ready:'已就绪',loading:'正在读取',error:'读取失败',unavailable:'暂无可用资源',idle:'未检查'})[status]||status;
      const note=key==='recommendation'&&['loading','error'].includes(status)?'使用内置默认配置，尚未获取实时推荐':'';
      return `<div data-training-input="${key}" data-status="${status}"><b>${title}</b><span>${escapeHtml(label)}</span>${note?`<small>${note}</small>`:''}${value.error?`<small>${escapeHtml(value.error)}</small>`:''}${['error','unavailable'].includes(status)?`<button type="button" class="btn mini" data-training-input-retry="${key}">重试</button>`:''}</div>`;
    }).join('');
    if(box.innerHTML!==html)box.innerHTML=html;
    if(!box.dataset.bound){box.dataset.bound='1';box.addEventListener('click',event=>{const key=event.target.closest('[data-training-input-retry]')?.dataset.trainingInputRetry;if(key)void retry(key);});}
    window.TrainingSubmitRuntime?.updateReadiness?.();
  }
  function stage(name,patch){
    const state=getState?.()||{},pid=String(projectId?.()||'');
    if(!state.trainingCreationLoading||state.trainingCreationLoading.projectId!==pid)state.trainingCreationLoading={projectId:pid};
    state.trainingCreationLoading[name]={...(state.trainingCreationLoading[name]||{}),...patch};
    paintStages();
  }
  async function retry(name){
    if(!liveOpening())return null;
    try{
      if(name==='resources')return await hydrateOptions({force:true,requireTrainable:false});
      if(name==='recommendation')return await hydrateRecommendation({force:true});
      return await hydratePreflight(activeOpening.aid,{force:true});
    }catch(error){return null;}
  }
  function diagnostics(){return JSON.parse(JSON.stringify(getState?.()?.trainingCreationLoading||{}));}
  const projectContext = () => {
    const state = getState?.() || {};
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目尚未加载完成');
    const projectKey = String(pid);
    if (commonProjectId && commonProjectId !== projectKey) {
      commonLoadedAt = 0;
      recommendationLoadedAt = 0;
      state.rec = null;
      state.targets = [];
      optionsController?.abort?.('project-changed');
      recommendationController?.abort?.('project-changed');
      optionsController = null;
      recommendationController = null;
      optionsInflight = null;
      recommendationInflight = null;
    }
    commonProjectId = projectKey;
    return {state, pid, projectKey};
  };

  const hydrateOptions = async ({force = false, requireTrainable = true, revalidate = false, maxAgeMs = COMMON_INPUT_TTL_MS} = {}) => {
    const {state, pid, projectKey} = projectContext();
    const age = Date.now() - Number(commonLoadedAt || 0);
    const fresh = commonLoadedAt > 0 && age >= 0 && age < Math.max(0, Number(maxAgeMs) || 0);
    const usable = requireTrainable
      ? trainingOptionsHydrated(state.targets)
      : Array.isArray(state.targets) && state.targets.length > 0;
    if (!force && (fresh || (!revalidate && usable && !commonLoadedAt))) {if(!commonLoadedAt)commonLoadedAt=Date.now();stage('resources',{status:trainingOptionsHydrated(state.targets)?'ready':'unavailable',cacheHit:true});return state.targets || [];}
    if (optionsInflight?.projectKey === projectKey) return optionsInflight.promise;

    const started=clockNow();stage('resources',{status:'loading',error:'',cacheHit:false,url:'/api/training_options',requestCount:Number(state.trainingCreationLoading?.resources?.requestCount||0)+1});
    optionsController = new AbortController();
    const controller = optionsController;
    const task = withRequestDeadline(signal=>request(`/api/training_options?project_id=${encodeURIComponent(pid)}`, {signal}),{timeoutMs:requestTimeoutMs,label:'训练资源准备',signal:controller.signal})
      .then(optionsResult => {
        if (destroyed || controller.signal.aborted || String(projectId?.() || '') !== projectKey) return getState?.()?.targets || [];
        const liveState = getState?.() || state;
        liveState.targets = optionsResult?.targets || [];
        commonLoadedAt = Date.now();
        commonProjectId = projectKey;
        stage('resources',{status:trainingOptionsHydrated(liveState.targets)?'ready':'unavailable',durationMs:Math.round(clockNow()-started),jsonBytes:jsonSize(optionsResult),error:''});
        if(liveOpening())window.applyTrainingCreationResources?.();
        return liveState.targets;
      })
      .catch(error=>{if(!destroyed&&String(projectId?.()||'')===projectKey&&!controller.signal.aborted)stage('resources',{status:'error',durationMs:Math.round(clockNow()-started),error:String(error.message||error)});throw error;})
      .finally(() => {
        if (optionsInflight?.promise === task) optionsInflight = null;
        if (optionsController === controller) optionsController = null;
      });
    optionsInflight = {projectKey, promise: task};
    return task;
  };

  const hydrateRecommendation = async ({force = false} = {}) => {
    const {state, projectKey} = projectContext();
    if (!force && state.rec != null && (!recommendationLoadedAt||Date.now()-recommendationLoadedAt<60000)){if(!recommendationLoadedAt)recommendationLoadedAt=Date.now();stage('recommendation',{status:'ready',cacheHit:true,error:''});return state.rec;}
    if (recommendationInflight?.projectKey === projectKey) return recommendationInflight.promise;

    const started=clockNow();stage('recommendation',{status:'loading',error:'',cacheHit:false,url:'/api/system/recommendation',requestCount:Number(state.trainingCreationLoading?.recommendation?.requestCount||0)+1});
    recommendationController = new AbortController();
    const controller = recommendationController;
    const task = withRequestDeadline(signal=>request('/api/system/recommendation', {signal}),{timeoutMs:requestTimeoutMs,label:'训练推荐配置',signal:controller.signal})
      .then(recommendationResult => {
        if (destroyed || controller.signal.aborted || String(projectId?.() || '') !== projectKey) return getState?.()?.rec ?? null;
        const liveState = getState?.() || state;
        liveState.rec = recommendationResult;
        recommendationLoadedAt=Date.now();
        stage('recommendation',{status:'ready',durationMs:Math.round(clockNow()-started),jsonBytes:jsonSize(recommendationResult),error:''});
        return recommendationResult;
      })
      .catch(error=>{if(!destroyed&&String(projectId?.()||'')===projectKey&&!controller.signal.aborted)stage('recommendation',{status:'error',durationMs:Math.round(clockNow()-started),error:String(error.message||error)});throw error;})
      .finally(() => {
        if (recommendationInflight?.promise === task) recommendationInflight = null;
        if (recommendationController === controller) recommendationController = null;
      });
    recommendationInflight = {projectKey, promise: task};
    return task;
  };

  const hydrate = async ({force = false, requireTrainable = true, revalidateOptions = false} = {}) => {
    const {state} = projectContext();
    const ready = requireTrainable
      ? trainingCreationInputsReady(state)
      : Array.isArray(state.targets) && state.targets.length > 0 && state.rec != null;
    if (!force && !revalidateOptions && ready) return state;

    await Promise.all([
      hydrateOptions({force, requireTrainable, revalidate: revalidateOptions}),
      hydrateRecommendation({force}),
    ]);
    const result = getState?.() || state;
    if (requireTrainable && !trainingOptionsHydrated(result.targets)) {
      throw new Error('没有发现可用的训练目标。请先到「训练资源」页面读取环境，确认本机或远程训练节点已就绪后重试。');
    }
    return result;
  };

  const hydrateCommon = async ({force = false, maxAgeMs = COMMON_INPUT_TTL_MS} = {}) => {
    const {state, projectKey} = projectContext();
    const age = Date.now() - Number(commonLoadedAt || 0);
    if (!force && commonLoadedAt > 0 && commonProjectId === projectKey && age >= 0 && age < Math.max(0, Number(maxAgeMs) || 0)) {
      return state;
    }
    await hydrateOptions({force, requireTrainable: false, revalidate: !force, maxAgeMs});
    if ((getState?.() || state).rec == null) void hydrateRecommendation().catch(() => {});
    return getState?.() || state;
  };

  const prewarm = async (aid = '', {includePreflight = true} = {}) => {
    if (destroyed) return null;
    const algorithmId = String(aid || '');
    const state = getState?.() || {};
    const algorithm = algorithmId
      ? (state.algorithms || []).find(item => String(item?.id || '') === algorithmId)
      : null;
    const externalChangLian = Boolean(algorithm)
      && String(algorithm?.source_type || '').toUpperCase() === 'EXTERNAL'
      && ['CHANG_LIAN', 'CHANGLIAN'].includes(String(algorithm?.provider_type || '').toUpperCase());
    const key = String(projectId?.()||'')+':'+(externalChangLian && includePreflight ? algorithmId : '__common__');
    if (prewarmInflight.has(key)) return prewarmInflight.get(key);
    const task = (async () => {
      const jobs = [hydrateOptions({requireTrainable:false,revalidate:true}), hydrateRecommendation()];
      const externalPreflightFresh = externalChangLian
        && typeof preflightFresh === 'function'
        && preflightFresh(algorithmId) === true;
      if (includePreflight && externalChangLian && !externalPreflightFresh && typeof preflight === 'function') {
        jobs.push(hydratePreflight(algorithmId));
      }
      return Promise.all(jobs);
    })().catch(() => null).finally(() => prewarmInflight.delete(key));
    prewarmInflight.set(key, task);
    return task;
  };

  const preflightInflight=new Map();
  async function hydratePreflight(aid,{force=false}={}){
    const project=String(projectId?.()||''),key=project+':'+aid;
    const algorithm=(getState?.()?.algorithms||[]).find(row=>String(row.id)===String(aid));
    const external=String(algorithm?.source_type||'').toUpperCase()==='EXTERNAL'&&['CHANG_LIAN','CHANGLIAN'].includes(String(algorithm?.provider_type||'').toUpperCase());
    if(!external||!force&&preflightFresh?.(aid)===true){stage('preflight',{status:'ready',error:'',cacheHit:true});return null;}
    if(preflightInflight.has(key))return preflightInflight.get(key);
    stage('preflight',{status:'loading',error:''});const started=clockNow();
    const pending=withRequestDeadline(signal=>preflight(aid,{signal}),{timeoutMs:requestTimeoutMs,label:'算法状态核验'})
      .then(result=>{if(String(projectId?.()||'')===project&&activeOpening?.aid===String(aid))stage('preflight',{status:'ready',durationMs:Math.round(clockNow()-started),error:''});return result;})
      .catch(error=>{if(String(projectId?.()||'')===project&&activeOpening?.aid===String(aid))stage('preflight',{status:'error',durationMs:Math.round(clockNow()-started),error:String(error.message||error)});throw error;})
      .finally(()=>preflightInflight.delete(key));preflightInflight.set(key,pending);return pending;
  }
  const start = async aid => {
    const token=++openEpoch,project=String(projectId?.()||''),started=clockNow();
    projectContext();
    const opened=await openForm(aid);
    if(destroyed||token!==openEpoch||project!==String(projectId?.()||''))return null;
    const root=typeof document==='undefined'?null:document.querySelector('.train429-create');
    activeOpening={token,project,aid:String(aid),root};
    stage('resources',{openedInMs:Math.round(clockNow()-started)});
    // Start independent loads after the real form has mounted. Neither recommendation
    // nor preflight success is invented; submission still uses its canonical checks.
    void hydrateOptions({requireTrainable:false,revalidate:true}).catch(()=>{});
    void hydrateRecommendation().catch(()=>{});
    void hydratePreflight(aid).catch(()=>{});
    paintStages();return opened;
  };

  window.startAlgorithmTraining429 = start;
  window.startAlgorithmTraining423 = start;
  const runtime = Object.freeze({
    hydrate,
    hydrateCommon,
    hydrateOptions,
    hydrateRecommendation,
    diagnostics,
    retry,
    start,
    prewarm,
    build: 'training-create-hydration-20261028',
    destroy() {
      destroyed = true;
      openEpoch += 1;
      activeOpening=null;
      optionsController?.abort?.('runtime-destroyed');
      recommendationController?.abort?.('runtime-destroyed');
      optionsController = null;
      recommendationController = null;
      optionsInflight = null;
      recommendationInflight = null;
      prewarmInflight.clear();
      if (window.startAlgorithmTraining429 === start) window.startAlgorithmTraining429 = openForm;
      if (window.TrainingCreateHydrationRuntime === runtime) window.TrainingCreateHydrationRuntime = null;
      window.__trainingCreateHydrationInstalled = false;
    },
  });
  window.TrainingCreateHydrationRuntime = runtime;
  window.__trainingCreateHydrationInstalled = true;
  return runtime;
}
