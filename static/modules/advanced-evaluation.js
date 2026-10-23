import {withRequestDeadline} from './api.js?v=20261021s';
import {eligibleScenarioModels, evaluationTruth} from './scenario-evaluation.js?v=20261022a';

const escape=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const statusNames={passed:'检查通过',risk:'存在风险',needs_review:'需要人工确认',not_checked:'未执行检查',insufficient_evidence:'证据不足'};
export function trustAnalysisHtml(analysis={}) {
  const checks=analysis.checks||[];
  return `<div class="advanced-trust-grid">${checks.map(row=>`<section class="panel advanced-trust-check" data-trust-check="${escape(row.code)}"><header><h3>${escape(row.title)}</h3><span class="advanced-status ${escape(row.status)}">${escape(statusNames[row.status]||'证据不足')}</span></header>${row.explanation?`<p>${escape(row.explanation)}</p>`:''}${row.count?`<details><summary>查看 ${escape(row.count)} 项明细</summary><ul>${(row.details||[]).map(item=>`<li>${escape(item.reason||item.relation||item.content_sha256||'冻结证据')} ${(item.members||[]).map(member=>`<span>${escape(member.image_id)} · ${escape((member.roles||[]).join('/'))}</span>`).join('')}</li>`).join('')}</ul>${row.count>(row.details?.length||0)?`<div class="row"><button class="btn small" data-trust-page="-1" ${!row.offset?'disabled':''}>上一页</button><span>${Number(row.offset||0)+1}–${Math.min(row.count,Number(row.offset||0)+Number(row.limit||20))}</span><button class="btn small" data-trust-page="1" ${Number(row.offset||0)+Number(row.limit||20)>=row.count?'disabled':''}>下一页</button></div>`:''}</details>`:''}</section>`).join('')}</div><section class="panel advanced-coverage"><h3>冻结 Test 类别覆盖</h3>${(analysis.coverage||[]).map(row=>`<span>${escape(row.label)} · ${row.status==='covered'?`${escape(row.image_count)} 张`:'未覆盖'}</span>`).join('')||'<p>未记录可信类别覆盖</p>'}</section>`;
}

// Advanced presentation only. Existing APIs/evaluation/SVG/task owners retain authority.
export function installAdvancedEvaluation({getState,api}) {
  let project='',models=[],algorithm=null,selected='',tab='trust',analysis=null,error='',loading=false;
  let controller=null,sequence=0,detailOffset=0;
  let samples=null,sampleOffset=0,sampleIssue='',sampleSort='severity';
  const state=getState();
  const currentProject=()=>String(state.projectId||state.currentProjectId||state.project?.id||state.currentProject?.id||'');
  const root=()=>document.querySelector('[data-advanced-evaluation]');
  function deactivate(){controller?.abort();sequence++;loading=false;window.QualityDetectionWorkbenchRuntime?.deactivate?.();}
  async function request(path,signal){return withRequestDeadline(inner=>api(path,{signal:inner}),{signal,label:'高级评测证据读取'});}
  async function load({refreshModels=false}={}) {
    controller?.abort();controller=new AbortController();const signal=controller.signal,epoch=++sequence,pid=currentProject();if(project&&project!==pid){models=[];algorithm=null;analysis=null;samples=null;selected='';}
    loading=true;error='';render();
    const live=()=>epoch===sequence&&!signal.aborted&&pid===currentProject()&&!!root();
    try{
      if(refreshModels||project!==pid){const response=await request(`/api/v12/projects/${encodeURIComponent(pid)}/test_models?model_scope=scenario`,signal);if(!live())return;if(project!==pid){selected='';analysis=null;algorithm=null;}models=eligibleScenarioModels(response.items||[]).sort((a,b)=>String(b.finished_at||b.created_at||'').localeCompare(String(a.finished_at||a.created_at||''))||String(b.version_id).localeCompare(String(a.version_id)));project=pid;}
      if(!models.some(model=>`${model.algorithm_id}:${model.version_id}`===selected))selected=models[0]?`${models[0].algorithm_id}:${models[0].version_id}`:'';
      const model=models.find(row=>`${row.algorithm_id}:${row.version_id}`===selected);
      if(!model){analysis=null;algorithm=null;return;}
      const base=`/api/v12/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(model.algorithm_id)}`;
      const [detail,trust]=await Promise.all([request(`${base}/versions/${encodeURIComponent(model.version_id)}/evaluation/report`,signal),request(`${base}/versions/${encodeURIComponent(model.version_id)}/evaluation/trust?offset=${detailOffset}&limit=20`,signal)]);
      if(!live())return;
      if(String((detail.algorithm||detail).id)!==String(model.algorithm_id)||trust.project_id!==pid||trust.algorithm_id!==model.algorithm_id||trust.version_id!==model.version_id)throw new Error('高级评测响应身份不一致');
      algorithm=detail.algorithm||detail;analysis=trust.analysis;
      if(tab==='diagnostics'){
        const result=await request(`${base}/versions/${encodeURIComponent(model.version_id)}/evaluation/samples?offset=${sampleOffset}&limit=24&issue=${encodeURIComponent(sampleIssue)}&sort=${sampleSort}`,signal);
        if(!live())return;
        const version=algorithm.versions?.find(row=>row.id===model.version_id);
        if(result.evaluation_id!==version?.evaluation?.evaluation_id)throw new Error('样本与报告身份已变化，请刷新');
        samples=result;
      }
    }catch(cause){if(live()&&cause.name!=='AbortError')error=String(cause.message||cause);}
    finally{if(live()){loading=false;render();}}
  }
  function render(){
    const host=root();if(!host)return;
    const model=models.find(row=>`${row.algorithm_id}:${row.version_id}`===selected),version=algorithm?.versions?.find(row=>row.id===model?.version_id);
    const algorithms=[...new Set(models.map(row=>row.algorithm_id))];
    host.innerHTML=`<header class="advanced-heading"><div><h2>模型深度评测</h2><p>冻结数据可信度 · 逐框诊断 · 版本演进</p></div><button class="btn" data-advanced-retry ${loading?'disabled':''}>${loading?'<i class="loading-spinner"></i>读取中':'刷新证据'}</button></header><div class="advanced-selectors"><label>算法<select class="select" data-advanced-algorithm>${algorithms.map(id=>`<option value="${escape(id)}" ${id===model?.algorithm_id?'selected':''}>${escape(models.find(row=>row.algorithm_id===id)?.algorithm_name||id)}</option>`).join('')}</select></label><label>成功训练版本<select class="select" data-advanced-version>${models.filter(row=>row.algorithm_id===model?.algorithm_id).map(row=>`<option value="${escape(`${row.algorithm_id}:${row.version_id}`)}" ${row===model?'selected':''}>${escape(row.version_name||row.version_id)}</option>`).join('')}</select></label><div class="advanced-benchmark"><span>冻结测试基准</span><strong>${escape(version?.evaluation?.benchmark_scope?.scope_id||'尚未取得可信评测证据')}</strong></div></div><nav class="advanced-tabs" role="tablist">${[['trust','数据可信度'],['diagnostics','错误诊断'],['comparison','版本对比'],['iteration','复核与迭代']].map(([key,title])=>`<button class="btn ${tab===key?'primary':'soft'}" role="tab" aria-selected="${tab===key}" data-advanced-tab="${key}" ${!['trust','diagnostics'].includes(key)?'disabled':''}>${title}</button>`).join('')}</nav>${error?`<div class="alert err" role="alert">${escape(error)} <button class="btn small" data-advanced-retry>重试</button></div>`:''}${loading?'<p role="status"><i class="loading-spinner"></i> 正在核验冻结评测证据…</p>':''}<div data-advanced-body>${tab==='diagnostics'?'<div data-advanced-diagnostics></div>':analysis?trustAnalysisHtml(analysis):!loading?'<div class="scn-empty">尚未取得可核验的成功训练版本与评测证据</div>':''}</div>`;
    if(tab==='diagnostics'&&!loading)renderDiagnostics(host,model,version);
    host.onclick=event=>{const chosen=event.target.closest('[data-advanced-tab]');if(chosen){tab=chosen.dataset.advancedTab;window.QualityDetectionWorkbenchRuntime?.deactivate?.();void load();return;}const samplePage=event.target.closest('[data-sample-page]');if(samplePage){sampleOffset=Math.max(0,sampleOffset+24*Number(samplePage.dataset.samplePage));void load();return;}if(event.target.closest('[data-advanced-retry]'))void load({refreshModels:true});const page=event.target.closest('[data-trust-page]');if(page){detailOffset=Math.max(0,detailOffset+Number(page.dataset.trustPage)*20);void load();}};
    host.onchange=event=>{if(event.target.matches('[data-sample-issue],[data-sample-sort]')){if(event.target.matches('[data-sample-issue]'))sampleIssue=event.target.value;else sampleSort=event.target.value;sampleOffset=0;void load();return;}if(event.target.matches('[data-advanced-algorithm]')){const next=models.find(row=>row.algorithm_id===event.target.value);selected=next?`${next.algorithm_id}:${next.version_id}`:'';}else if(event.target.matches('[data-advanced-version]'))selected=event.target.value;else return;detailOffset=0;sampleOffset=0;samples=null;analysis=null;algorithm=null;void load();};
  }
  function renderDiagnostics(host,model,version){
    const body=host.querySelector('[data-advanced-diagnostics]');if(!body)return;
    if(!version||!evaluationTruth(version.evaluation,model).trusted){body.innerHTML='<div class="scn-empty">尚未取得本版本可信独立评测，不计算准确率或错误类型。</div>';return;}
    if(!samples){body.innerHTML='<p>尚未取得正式样本证据，请重试读取。</p>';return;}
    const total=Number(samples.total||0);
    body.innerHTML=`<div class="advanced-sample-toolbar"><label>全体已存样本筛选<select class="select" data-sample-issue>${[['','全部'],['tp','正确匹配'],['fp','误检'],['fn','漏检'],['wrong_class','类别错误线索'],['localization','定位偏差线索'],['duplicate','重复检测线索'],['low_confidence','低置信度']].map(([value,label])=>`<option value="${value}" ${value===sampleIssue?'selected':''}>${label}</option>`).join('')}</select></label><label>排序<select class="select" data-sample-sort><option value="severity">漏检优先，其次误检</option><option value="high_confidence_fp" ${sampleSort==='high_confidence_fp'?'selected':''}>高置信度误检优先（已有框证据）</option></select></label><span>${samples.cohort_complete?'完整逐图结果':'历史仅保留部分问题图片，其他图片结果未知'} · ${total} 张</span><button class="btn small" data-sample-page="-1" ${sampleOffset===0?'disabled':''}>上一批</button><button class="btn small" data-sample-page="1" ${sampleOffset+24>=total?'disabled':''}>下一批</button></div><p>以下图层与类别筛选仅作用于当前批次；显示阈值不改变正式统计。未保留框和截断证据均不能补造。</p><div data-advanced-evidence></div>`;
    window.QualityDetectionWorkbenchRuntime?.mountEvaluationEvidence(body.querySelector('[data-advanced-evidence]'),{model,version,rows:samples.items||[]});
  }
  function mount(){const view=document.getElementById('view');if(!view)return;if(!root())view.innerHTML='<div class="advanced-evaluation" data-advanced-evaluation></div>';render();void load({refreshModels:project!==currentProject()||!models.length});}
  return {mount,deactivate};
}
