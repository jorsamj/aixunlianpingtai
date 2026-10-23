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
  let compareSelected='',comparison=null,sourceVersion=null,comparisonOffset=0,comparisonCategory='',comparisonSample=0;
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
      if(tab==='comparison'&&compareSelected){
        const [result,source]=await Promise.all([
          request(`${base}/versions/${encodeURIComponent(model.version_id)}/evaluation/deep-compare/${encodeURIComponent(compareSelected)}?offset=${comparisonOffset}&limit=24&category=${comparisonCategory}`,signal),
          request(`${base}/versions/${encodeURIComponent(compareSelected)}/evaluation/report`,signal)]);
        if(!live())return;
        if(result.comparison?.current_version_id!==model.version_id||result.comparison?.source_version_id!==compareSelected)throw new Error('版本对比身份已变化');
        comparison=result.comparison;sourceVersion=(source.algorithm||source).versions?.find(row=>row.id===compareSelected);comparisonSample=0;
      }
    }catch(cause){if(live()&&cause.name!=='AbortError')error=String(cause.message||cause);}
    finally{if(live()){loading=false;render();}}
  }
  function render(){
    const host=root();if(!host)return;if(host.querySelector('.scenario-workbench'))window.QualityDetectionWorkbenchRuntime?.deactivate?.();
    const model=models.find(row=>`${row.algorithm_id}:${row.version_id}`===selected),version=algorithm?.versions?.find(row=>row.id===model?.version_id);
    const algorithms=[...new Set(models.map(row=>row.algorithm_id))];
    host.innerHTML=`<header class="advanced-heading"><div><h2>模型深度评测</h2><p>冻结数据可信度 · 逐框诊断 · 版本演进</p></div><button class="btn" data-advanced-retry ${loading?'disabled':''}>${loading?'<i class="loading-spinner"></i>读取中':'刷新证据'}</button></header><div class="advanced-selectors"><label>算法<select class="select" data-advanced-algorithm>${algorithms.map(id=>`<option value="${escape(id)}" ${id===model?.algorithm_id?'selected':''}>${escape(models.find(row=>row.algorithm_id===id)?.algorithm_name||id)}</option>`).join('')}</select></label><label>成功训练版本<select class="select" data-advanced-version>${models.filter(row=>row.algorithm_id===model?.algorithm_id).map(row=>`<option value="${escape(`${row.algorithm_id}:${row.version_id}`)}" ${row===model?'selected':''}>${escape(row.version_name||row.version_id)}</option>`).join('')}</select></label><div class="advanced-benchmark"><span>冻结测试基准</span><strong>${escape(version?.evaluation?.benchmark_scope?.scope_id||'尚未取得可信评测证据')}</strong></div></div><nav class="advanced-tabs" role="tablist">${[['trust','数据可信度'],['diagnostics','错误诊断'],['comparison','版本对比'],['iteration','复核与迭代']].map(([key,title])=>`<button class="btn ${tab===key?'primary':'soft'}" role="tab" aria-selected="${tab===key}" data-advanced-tab="${key}" ${!['trust','diagnostics','comparison'].includes(key)?'disabled':''}>${title}</button>`).join('')}</nav>${error?`<div class="alert err" role="alert">${escape(error)} <button class="btn small" data-advanced-retry>重试</button></div>`:''}${loading?'<p role="status"><i class="loading-spinner"></i> 正在核验冻结评测证据…</p>':''}<div data-advanced-body>${tab==='diagnostics'?'<div data-advanced-diagnostics></div>':tab==='comparison'?'<div data-advanced-comparison></div>':analysis?trustAnalysisHtml(analysis):!loading?'<div class="scn-empty">尚未取得可核验的成功训练版本与评测证据</div>':''}</div>`;
    if(tab==='diagnostics'&&!loading)renderDiagnostics(host,model,version);
    if(tab==='comparison'&&!loading)renderComparison(host,model,version);
    host.onclick=event=>{if(event.target.closest('[data-add-comparison]')){compareSelected=models.find(row=>row.algorithm_id===model?.algorithm_id&&row.version_id!==model?.version_id)?.version_id||'';comparison=null;void load();return;}const cp=event.target.closest('[data-comparison-page]');if(cp){comparisonOffset=Math.max(0,comparisonOffset+24*Number(cp.dataset.comparisonPage));void load();return;}const sample=event.target.closest('[data-comparison-sample]');if(sample){comparisonSample=Number(sample.dataset.comparisonSample);renderComparison(host,model,version);return;}const chosen=event.target.closest('[data-advanced-tab]');if(chosen){tab=chosen.dataset.advancedTab;window.QualityDetectionWorkbenchRuntime?.deactivate?.();void load();return;}const samplePage=event.target.closest('[data-sample-page]');if(samplePage){sampleOffset=Math.max(0,sampleOffset+24*Number(samplePage.dataset.samplePage));void load();return;}if(event.target.closest('[data-advanced-retry]'))void load({refreshModels:true});const page=event.target.closest('[data-trust-page]');if(page){detailOffset=Math.max(0,detailOffset+Number(page.dataset.trustPage)*20);void load();}};
    host.onchange=event=>{if(event.target.matches('[data-comparison-version],[data-comparison-category]')){if(event.target.matches('[data-comparison-version]'))compareSelected=event.target.value;else comparisonCategory=event.target.value;comparisonOffset=0;comparison=null;void load();return;}if(event.target.matches('[data-sample-issue],[data-sample-sort]')){if(event.target.matches('[data-sample-issue]'))sampleIssue=event.target.value;else sampleSort=event.target.value;sampleOffset=0;void load();return;}if(event.target.matches('[data-advanced-algorithm]')){const next=models.find(row=>row.algorithm_id===event.target.value);selected=next?`${next.algorithm_id}:${next.version_id}`:'';}else if(event.target.matches('[data-advanced-version]'))selected=event.target.value;else return;detailOffset=0;sampleOffset=0;samples=null;analysis=null;algorithm=null;compareSelected='';comparison=null;void load();};
  }
  function renderDiagnostics(host,model,version){
    const body=host.querySelector('[data-advanced-diagnostics]');if(!body)return;
    if(!version||!evaluationTruth(version.evaluation,model).trusted){body.innerHTML='<div class="scn-empty">尚未取得本版本可信独立评测，不计算准确率或错误类型。</div>';return;}
    if(!samples){body.innerHTML='<p>尚未取得正式样本证据，请重试读取。</p>';return;}
    const total=Number(samples.total||0);
    body.innerHTML=`<div class="advanced-sample-toolbar"><label>全体已存样本筛选<select class="select" data-sample-issue>${[['','全部'],['tp','正确匹配'],['fp','误检'],['fn','漏检'],['wrong_class','类别错误线索'],['localization','定位偏差线索'],['duplicate','重复检测线索'],['low_confidence','低置信度']].map(([value,label])=>`<option value="${value}" ${value===sampleIssue?'selected':''}>${label}</option>`).join('')}</select></label><label>排序<select class="select" data-sample-sort><option value="severity">漏检优先，其次误检</option><option value="high_confidence_fp" ${sampleSort==='high_confidence_fp'?'selected':''}>高置信度误检优先（已有框证据）</option></select></label><span>${samples.cohort_complete?'完整逐图结果':'历史仅保留部分问题图片，其他图片结果未知'} · ${total} 张</span><button class="btn small" data-sample-page="-1" ${sampleOffset===0?'disabled':''}>上一批</button><button class="btn small" data-sample-page="1" ${sampleOffset+24>=total?'disabled':''}>下一批</button></div><p>以下图层与类别筛选仅作用于当前批次；显示阈值不改变正式统计。未保留框和截断证据均不能补造。</p><details id="scenarioAnalysis64" class="panel"><summary>类别指标、混淆矩阵与置信度曲线</summary><div data-scn-analysis-body></div></details><div data-advanced-evidence></div>`;
    window.QualityDetectionWorkbenchRuntime?.mountEvaluationEvidence(body.querySelector('[data-advanced-evidence]'),{model,version,rows:samples.items||[]});
  }
  function renderComparison(host,model,version){
    const body=host.querySelector('[data-advanced-comparison]');if(!body)return;
    const choices=models.filter(row=>row.algorithm_id===model?.algorithm_id&&row.version_id!==model?.version_id);
    if(!compareSelected){body.innerHTML=`<div class="scn-empty"><b>按相同冻结基准比较成功训练版本</b><p>比较正式指标和逐样本改善、退步；证据缺失保持未知。</p><button class="btn primary" data-add-comparison ${!choices.length?'disabled':''}>添加对比版本</button>${!choices.length?'<p>当前算法尚无其他可验证的成功版本</p>':''}</div>`;return;}
    const names={improved:'改善样本',regressed:'退步样本',persistent_error:'持续错误',persistent_correct:'持续正确',unknown:'证据不足'};
    const selectedModel=choices.find(row=>row.version_id===compareSelected);
    body.innerHTML=`<div class="advanced-sample-toolbar"><label>对比旧版本<select class="select" data-comparison-version>${choices.map(row=>`<option value="${escape(row.version_id)}" ${row.version_id===compareSelected?'selected':''}>${escape(row.version_name||row.version_id)}</option>`).join('')}</select></label><span>旧版 → 当前 ${escape(model?.version_name||model?.version_id)}</span></div><div data-comparison-content></div>`;
    const content=body.querySelector('[data-comparison-content]');
    if(!comparison){content.innerHTML='<p>尚未取得版本对比证据，请重试。</p>';return;}
    if(!comparison.comparable){const reasons={benchmark_trust_not_verified:'冻结身份不完整或存在已证实的数据/GT风险',benchmark_scope_mismatch:'冻结 Benchmark 或 GT 身份不同',benchmark_evidence_missing:'缺少完整冻结身份',benchmark_input_binding_missing:'缺少已执行输入证据',evaluation_protocol_mismatch:'评测协议不同',class_identity_ambiguous:'类别映射不明确',evaluation_missing:'缺少有效评测'};content.innerHTML=`<div class="alert warn"><b>不能计算模型提升</b><p>${escape((comparison.reason_codes||[]).map(code=>reasons[code]||code).join('；'))}</p></div>`;return;}
    const value=n=>Number.isFinite(n)?`${(n*100).toFixed(1)}%`:'未记录';
    const delta=n=>Number.isFinite(n)?`${n>=0?'+':''}${(n*100).toFixed(1)} 个百分点`:'未记录';
    const metrics=comparison.metrics||{};
    content.innerHTML=`<div class="advanced-comparison-metrics">${[['precision','Precision'],['recall','Recall'],['map50','mAP50'],['map50_95','mAP50-95']].map(([key,label])=>`<section class="panel"><b>${label}</b><p>${value(metrics[key]?.before)} → ${value(metrics[key]?.after)}</p><strong>${delta(metrics[key]?.delta)}</strong></section>`).join('')}</div><p>正式 TP / FP / FN：${['before','after'].map(side=>{const counts=comparison.detection_counts?.[side]||{};return ['true_positive','false_positive','false_negative'].map(key=>Number.isFinite(counts[key])?counts[key]:'未记录').join(' / ')}).join(' → ')} · Micro F1：${value(comparison.detection_counts?.before?.micro_f1)} → ${value(comparison.detection_counts?.after?.micro_f1)}</p><p>同一冻结GT与评测协议的正式结果变化，不代表已满足业务发布要求。数据独立性风险仍须结合“数据可信度”。</p><details><summary>类别指标与退步证据</summary><div class="table-wrap"><table class="table"><thead><tr><th>类别</th><th>Precision 变化</th><th>Recall 变化</th><th>AP50 变化</th><th>AP50-95 变化</th><th>FP 变化</th><th>FN 变化</th></tr></thead><tbody>${(comparison.classes||[]).map(row=>`<tr><td>${escape(row.label)}${row.regressed?' · 退步':''}</td>${['precision','recall','map50','map50_95','false_positive','false_negative'].map(key=>`<td>${row.comparable?key.startsWith('false_')?(Number.isFinite(row.metrics?.[key]?.delta)?row.metrics[key].delta:'未覆盖'):delta(row.metrics?.[key]?.delta):'未覆盖'}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details><div class="advanced-sample-toolbar"><label>样本变化<select class="select" data-comparison-category><option value="">全部已存证据</option>${Object.entries(names).map(([key,label])=>`<option value="${key}" ${key===comparisonCategory?'selected':''}>${label} · ${Number(comparison.sample_counts?.[key]||0)}</option>`).join('')}</select></label><span>${comparison.sample_cohort_complete?'完整逐图对比':'部分历史证据，缺席图片不可推断正确'}</span><button class="btn small" data-comparison-page="-1" ${comparisonOffset===0?'disabled':''}>上一批</button><button class="btn small" data-comparison-page="1" ${comparisonOffset+24>=Number(comparison.total||0)?'disabled':''}>下一批</button></div><div class="advanced-comparison-samples">${(comparison.samples||[]).map((row,index)=>`<button class="btn ${index===comparisonSample?'primary':''}" data-comparison-sample="${index}">${escape(row.image_id)} · ${names[row.category]||'证据不足'}</button>`).join('')||'<p>尚无同身份逐图证据，不能从旧问题列表的缺席推断改善。</p>'}</div><div data-comparison-evidence></div>`;
    const sample=comparison.samples?.[comparisonSample],viewer=content.querySelector('[data-comparison-evidence]');
    if(sample?.category==='unknown'){viewer.innerHTML='<p>该图缺少同一冻结GT或双侧结果证据，不计算改善或退步。</p>';return;}
    if(sample?.after&&sample?.before&&version&&sourceVersion&&selectedModel){
      window.QualityDetectionWorkbenchRuntime?.mountEvaluationEvidence(viewer,{model,version,rows:[sample.after],comparison:{result:comparison,model:selectedModel,version:{...sourceVersion,evaluation:{...sourceVersion.evaluation,error_samples:[sample.before]}}}});
    }
  }
  function mount(){const view=document.getElementById('view');if(!view)return;if(!root())view.innerHTML='<div class="advanced-evaluation" data-advanced-evaluation></div>';render();void load({refreshModels:project!==currentProject()||!models.length});}
  return {mount,deactivate};
}
