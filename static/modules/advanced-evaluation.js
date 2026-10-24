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
  let reviewSampleId='',reviewMessage='',miningTaskId='',miningPreview=null,miningOffset=0,busy=false;
  let reviewHistory=[],eligibleMining=[];
  const state=getState();
  const currentProject=()=>String(state.projectId||state.currentProjectId||state.project?.id||state.currentProject?.id||'');
  const root=()=>document.querySelector('[data-advanced-evaluation]');
  function deactivate(){controller?.abort();sequence++;loading=false;window.QualityDetectionWorkbenchRuntime?.deactivate?.();}
  async function request(path,signal,options={}){return withRequestDeadline(inner=>api(path,{...options,signal:inner}),{signal,label:'高级评测证据读取'});}
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
      if(tab==='diagnostics'||tab==='iteration'){
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
      if(tab==='iteration'){
        const history=await request(`/api/v63/projects/${encodeURIComponent(pid)}/online-feedback?limit=100`,signal);
        if(!live())return;reviewHistory=(history.items||[]).filter(row=>row.source?.source_channel==='evaluation'&&row.source?.external_source===analysis?.evaluation_id);
      }
    }catch(cause){if(live()&&cause.name!=='AbortError')error=String(cause.message||cause);}
    finally{if(live()){loading=false;render();}}
  }
  function render(){
    const host=root();if(!host)return;if(host.querySelector('.scenario-workbench'))window.QualityDetectionWorkbenchRuntime?.deactivate?.();
    const model=models.find(row=>`${row.algorithm_id}:${row.version_id}`===selected),version=algorithm?.versions?.find(row=>row.id===model?.version_id);
    const algorithms=[...new Set(models.map(row=>row.algorithm_id))];
    host.innerHTML=`<header class="advanced-heading"><div><h2>模型深度评测</h2><p>冻结数据可信度 · 逐框诊断 · 版本演进</p></div><button class="btn" data-advanced-retry ${loading?'disabled':''}>${loading?'<i class="loading-spinner"></i>读取中':'刷新证据'}</button></header><div class="advanced-selectors"><label>算法<select class="select" data-advanced-algorithm>${algorithms.map(id=>`<option value="${escape(id)}" ${id===model?.algorithm_id?'selected':''}>${escape(models.find(row=>row.algorithm_id===id)?.algorithm_name||id)}</option>`).join('')}</select></label><label>成功训练版本<select class="select" data-advanced-version>${models.filter(row=>row.algorithm_id===model?.algorithm_id).map(row=>`<option value="${escape(`${row.algorithm_id}:${row.version_id}`)}" ${row===model?'selected':''}>${escape(row.version_name||row.version_id)}</option>`).join('')}</select></label><div class="advanced-benchmark"><span>冻结测试基准</span><strong>${escape(version?.evaluation?.benchmark_scope?.scope_id||'尚未取得可信评测证据')}</strong></div></div><nav class="advanced-tabs" role="tablist">${[['trust','数据可信度'],['diagnostics','错误诊断'],['comparison','版本对比'],['iteration','复核与迭代']].map(([key,title])=>`<button class="btn ${tab===key?'primary':'soft'}" role="tab" aria-selected="${tab===key}" data-advanced-tab="${key}" >${title}</button>`).join('')}</nav>${error?`<div class="alert err" role="alert">${escape(error)} <button class="btn small" data-advanced-retry>重试</button></div>`:''}${loading?'<p role="status"><i class="loading-spinner"></i> 正在核验冻结评测证据…</p>':''}<div data-advanced-body>${tab==='iteration'?'<div data-advanced-iteration></div>':tab==='diagnostics'?'<div data-advanced-diagnostics></div>':tab==='comparison'?'<div data-advanced-comparison></div>':analysis?trustAnalysisHtml(analysis):!loading?'<div class="scn-empty">尚未取得可核验的成功训练版本与评测证据</div>':''}</div>`;
    if(tab==='diagnostics'&&!loading)renderDiagnostics(host,model,version);
    if(tab==='comparison'&&!loading)renderComparison(host,model,version);
    if(tab==='iteration'&&!loading)renderIteration(host,model,version);
    host.onclick=event=>{const iterationButton=event.target.closest('[data-iteration-action]');if(iterationButton){void iterationAction(iterationButton.dataset.iterationAction,iterationButton);return;}if(event.target.closest('[data-review-current]')){reviewSampleId=window.QualityDetectionWorkbenchRuntime?.currentEvaluationSample?.()?.image_id||'';tab='iteration';window.QualityDetectionWorkbenchRuntime?.deactivate?.();void load();return;}if(event.target.closest('[data-add-comparison]')){compareSelected=models.find(row=>row.algorithm_id===model?.algorithm_id&&row.version_id!==model?.version_id)?.version_id||'';comparison=null;void load();return;}const cp=event.target.closest('[data-comparison-page]');if(cp){comparisonOffset=Math.max(0,comparisonOffset+24*Number(cp.dataset.comparisonPage));void load();return;}const sample=event.target.closest('[data-comparison-sample]');if(sample){comparisonSample=Number(sample.dataset.comparisonSample);renderComparison(host,model,version);return;}const chosen=event.target.closest('[data-advanced-tab]');if(chosen){tab=chosen.dataset.advancedTab;window.QualityDetectionWorkbenchRuntime?.deactivate?.();void load();return;}const samplePage=event.target.closest('[data-sample-page]');if(samplePage){sampleOffset=Math.max(0,sampleOffset+24*Number(samplePage.dataset.samplePage));void load();return;}if(event.target.closest('[data-advanced-retry]'))void load({refreshModels:true});const page=event.target.closest('[data-trust-page]');if(page){detailOffset=Math.max(0,detailOffset+Number(page.dataset.trustPage)*20);void load();}};
    host.onchange=event=>{if(event.target.matches('[data-comparison-version],[data-comparison-category]')){if(event.target.matches('[data-comparison-version]'))compareSelected=event.target.value;else comparisonCategory=event.target.value;comparisonOffset=0;comparison=null;void load();return;}if(event.target.matches('[data-sample-issue],[data-sample-sort]')){if(event.target.matches('[data-sample-issue]'))sampleIssue=event.target.value;else sampleSort=event.target.value;sampleOffset=0;void load();return;}if(event.target.matches('[data-advanced-algorithm]')){const next=models.find(row=>row.algorithm_id===event.target.value);selected=next?`${next.algorithm_id}:${next.version_id}`:'';}else if(event.target.matches('[data-advanced-version]'))selected=event.target.value;else return;detailOffset=0;sampleOffset=0;samples=null;analysis=null;algorithm=null;compareSelected='';comparison=null;void load();};
  }
  function renderDiagnostics(host,model,version){
    const body=host.querySelector('[data-advanced-diagnostics]');if(!body)return;
    if(!version||!evaluationTruth(version.evaluation,model).trusted){body.innerHTML='<div class="scn-empty">尚未取得本版本可信独立评测，不计算准确率或错误类型。</div>';return;}
    if(!samples){body.innerHTML='<p>尚未取得正式样本证据，请重试读取。</p>';return;}
    const total=Number(samples.total||0);
    body.innerHTML=`<div class="advanced-sample-toolbar"><label>全体已存样本筛选<select class="select" data-sample-issue>${[['','全部'],['tp','正确匹配'],['fp','误检'],['fn','漏检'],['wrong_class','类别错误线索'],['localization','定位偏差线索'],['duplicate','重复检测线索'],['low_confidence','低置信度']].map(([value,label])=>`<option value="${value}" ${value===sampleIssue?'selected':''}>${label}</option>`).join('')}</select></label><label>排序<select class="select" data-sample-sort><option value="severity">漏检优先，其次误检</option><option value="high_confidence_fp" ${sampleSort==='high_confidence_fp'?'selected':''}>高置信度误检优先（已有框证据）</option></select></label><span>${samples.cohort_complete?'完整逐图结果':'历史仅保留部分问题图片，其他图片结果未知'} · ${total} 张 ${samples.filter_scope==='retained_box_evidence_only'&&!samples.filter_evidence_complete?'· 本筛选只覆盖已存框证据，其余未检查':''}</span><button class="btn small" data-sample-page="-1" ${sampleOffset===0?'disabled':''}>上一批</button><button class="btn small" data-sample-page="1" ${sampleOffset+24>=total?'disabled':''}>下一批</button></div><p>以下图层与类别筛选仅作用于当前批次；显示阈值不改变正式统计。未保留框和截断证据均不能补造。</p><details id="scenarioAnalysis64" class="panel"><summary>类别指标、混淆矩阵与置信度曲线</summary><div data-scn-analysis-body></div></details><button class="btn" data-review-current>加入复核</button><div data-advanced-evidence></div>`;
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
  function renderIteration(host,model,version){
    const body=host.querySelector('[data-advanced-iteration]');if(!body)return;
    const rows=samples?.items||[];if(!rows.some(row=>row.image_id===reviewSampleId))reviewSampleId=rows[0]?.image_id||'';
    const decision=version?.iteration_decision||{},candidateSet=version?.supplement_data_candidate_set;
    const labels={needs_data:'补充数据',continue_training:'继续训练',ready_for_business_validation:'业务验证',review_required:'人工处理'};
    const outcome=version?.feedback_adoption_outcome;
    body.innerHTML=`${reviewMessage?`<div class="alert soft" role="status">${escape(reviewMessage)}</div>`:''}<section class="panel advanced-review-card"><h3>冻结 Test 人工复核</h3><p>意见与正式GT分开保存。测试图片不能直接加入下一轮训练；GT更正通过原标注工作台，原冻结报告不被改写。</p><div class="advanced-selectors"><label>已保存的当前批次样本<select class="select" data-review-sample>${rows.map(row=>`<option value="${escape(row.image_id)}" ${row.image_id===reviewSampleId?'selected':''}>${escape(row.image)}</option>`).join('')}</select></label><label>复核意见<select class="select" data-review-observation><option value="">请选择</option><option value="model_error">确认模型错误</option><option value="gt_error">确认GT错误</option><option value="model_correct">确认模型正确</option><option value="unknown">暂无法确认</option><option value="hard_sample">标记困难样本（保持Test保护）</option></select></label><label>补充说明<input class="input" data-review-note maxlength="1000"></label></div><div class="row"><button class="btn primary" data-iteration-action="save-review" ${!reviewSampleId?'disabled':''}>保存复核意见</button><button class="btn" data-iteration-action="edit-gt" ${!reviewSampleId?'disabled':''}>打开原标注工作台</button></div><details><summary>最近100条反馈中的本评测复核记录 · ${reviewHistory.length}</summary>${reviewHistory.map(row=>`<p>${escape(row.source?.external_sample_id)} · ${escape(row.result?.review_observation||'待复核')} · ${escape(row.status)}</p>`).join('')||'<p>当前查询范围尚无复核记录</p>'}</details></section><section class="panel advanced-review-card"><h3>现有迭代建议</h3><p>${escape(labels[decision.decision]||'尚无可信的持久化迭代建议')} · ${escape((decision.weak_labels||[]).join('、'))}</p><p>确认建议不会创建训练任务。只有在原训练创建窗点击“开始训练”后才会提交。</p><div class="row"><button class="btn" data-iteration-action="confirm-decision" ${!decision.decision_id||algorithm?.current_version_id!==model?.version_id?'disabled':''}>确认当前建议</button><button class="btn" data-iteration-action="resume-decision" ${!version?.confirmed_iteration_action?'disabled':''}>打开已有流程</button><button class="btn primary" data-iteration-action="open-training" ${!candidateSet?.candidate_set_id?'disabled':''}>用于下一轮训练 · ${candidateSet?.material_ids?.length||0} 张已冻结候选</button></div></section><section class="panel advanced-review-card"><h3>非 Test 困难样本与审核采纳</h3><p>挖掘、队列、审核均沿用原AI标注任务。只有审核入库成功且GT未变化的样本才能冻结为Candidate Set。</p><div class="row"><button class="btn" data-iteration-action="load-eligible">选择可挖掘素材（最多100张）</button><button class="btn" data-iteration-action="start-mining" ${!eligibleMining.length?'disabled':''}>创建所选困难样本任务</button></div><div class="advanced-mining-choices">${eligibleMining.map(row=>{const id=typeof row==='string'?row:row.id||row.image_id;return `<label><input type="checkbox" data-mining-eligible="${escape(id)}">${escape(typeof row==='string'?row:row.filename||id)}</label>`}).join('')}</div><div class="advanced-sample-toolbar"><label>原困难样本任务 ID<input class="input" data-mining-task value="${escape(miningTaskId)}"></label><button class="btn" data-iteration-action="task-detail">查看原任务</button><button class="btn" data-iteration-action="task-review">打开原人工审核</button><button class="btn" data-iteration-action="preview-mining">检测已审核候选</button></div>${miningPreview?`<div class="advanced-mining-choices">${miningPreview.items.map(row=>`<label><input type="checkbox" data-mining-adopt="${escape(row.image_id)}" ${!row.eligible?'disabled':''}>${escape(row.image_id)} · ${row.eligible?'已审核可采纳':escape(row.reason)}</label>`).join('')||'<p>当前批次没有已审核候选</p>'}</div><div class="row"><button class="btn small" data-iteration-action="mining-prev" ${!miningOffset?'disabled':''}>上一批候选</button><button class="btn small" data-iteration-action="mining-next" ${!miningPreview.has_more?'disabled':''}>下一批候选</button></div><label><input type="checkbox" data-mining-confirm>已核对范围，确认冻结所选候选；不自动训练</label><button class="btn primary" data-iteration-action="adopt-mining">确认采纳为原 Candidate Set</button>`:''}</section><section class="panel advanced-review-card"><h3>既有反馈采纳效果追踪</h3>${outcome?`<p>原版本 ${escape(outcome.source_version_id)} → 当前 ${escape(outcome.new_version_id)} · 实际采纳 ${Number(outcome.adopted_candidate_count||0)} 项</p><p>${outcome.strictly_comparable?'同一冻结基准可作指标比较':'基准或证据不满足严格比较，不能宣称提升'}</p><p>分析仅作描述，不证明采纳样本导致改善。</p><details><summary>查看原持久化溯源证据</summary><pre class="advanced-outcome">${escape(JSON.stringify(outcome,null,2))}</pre></details>`:'<p>尚无该版本持久化 feedback_adoption_outcome；不推测训练改善。</p>'}</section>`;
  }
  async function iterationAction(action,button){
    if(busy)return;const host=root(),pid=currentProject(),selection=selected,epoch=sequence;
    const model=models.find(row=>`${row.algorithm_id}:${row.version_id}`===selection),version=algorithm?.versions?.find(row=>row.id===model?.version_id);
    if(!model||!version)return;
    const live=()=>root()===host&&host.isConnected&&pid===currentProject()&&selection===selected&&epoch===sequence;
    const base=`/api/v12/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(model.algorithm_id)}/versions/${encodeURIComponent(model.version_id)}`;
    const checked=[...host.querySelectorAll('[data-mining-adopt]:checked')].map(node=>node.dataset.miningAdopt);
    const mineIds=[...host.querySelectorAll('[data-mining-eligible]:checked')].map(node=>node.dataset.miningEligible);
    const sampleId=host.querySelector('[data-review-sample]')?.value||reviewSampleId;
    const observation=host.querySelector('[data-review-observation]')?.value,note=host.querySelector('[data-review-note]')?.value||'';
    const confirmed=host.querySelector('[data-mining-confirm]')?.checked;
    miningTaskId=host.querySelector('[data-mining-task]')?.value?.trim()||miningTaskId;
    const post=(path,body)=>request(path,controller?.signal,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    busy=true;button.disabled=true;const label=button.textContent;button.innerHTML='<i class="loading-spinner"></i> 处理中';
    try{
      if(action==='save-review'){
        if(!observation)throw new Error('请明确选择复核意见');
        const response=await post(`${base}/evaluation/review`,{expected_evaluation_id:version.evaluation.evaluation_id,image_id:sampleId,observation,note});
        if(!live())return;reviewMessage=response.feedback.status==='confirmed'?'复核意见已保存，正式GT未修改':'已加入待复核，正式GT未修改';reviewSampleId=sampleId;void load();return;
      }
      if(action==='edit-gt'){await window.openSupplementFeedbackAnnotation63?.(sampleId);return;}
      if(action==='load-eligible'){
        const result=await request(`/api/v64/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(model.algorithm_id)}/versions/${encodeURIComponent(model.version_id)}/hard-sample-mining/eligible?limit=100`,controller?.signal);
        if(!live())return;eligibleMining=result.items||[];reviewMessage=eligibleMining.length?'请明确选择需要挖掘的非Test素材':'没有符合条件的非Test未标注素材';
      }else if(action==='start-mining'){
        if(!mineIds.length)throw new Error('请先选择素材');
        const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify([pid,model.algorithm_id,model.version_id,[...mineIds].sort()])));
        if(!live())return;const key=[...new Uint8Array(digest)].map(n=>n.toString(16).padStart(2,'0')).join('');
        const task=await post(`/api/v64/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(model.algorithm_id)}/versions/${encodeURIComponent(model.version_id)}/hard-sample-mining`,{image_ids:mineIds,source:'existing',request_key:`p2-${key}`});
        if(!live())return;miningTaskId=task.task_id||task.id||'';reviewMessage=`任务 ${miningTaskId} 已进入原任务系统；尚未完成审核，不会自动训练`;
      }else if(action==='task-detail'||action==='task-review'){
        if(!miningTaskId)throw new Error('请输入原任务ID');
        if(action==='task-detail')await window.showAiTask60?.(miningTaskId);else await window.reviewAiLabel427?.(miningTaskId);return;
      }else if(['preview-mining','mining-prev','mining-next'].includes(action)){
        if(!miningTaskId)throw new Error('请输入原任务ID');
        miningOffset=action==='mining-prev'?Math.max(0,miningOffset-24):action==='mining-next'?miningOffset+24:0;
        const result=await request(`${base}/hard-sample-mining/${encodeURIComponent(miningTaskId)}/reviewed?offset=${miningOffset}&limit=24`,controller?.signal);
        if(!live())return;miningPreview=result;reviewMessage='已按真实审核journal、素材SHA与正式GT核验，尚未冻结候选';
      }else if(action==='adopt-mining'){
        if(!confirmed||!checked.length)throw new Error('请选择候选并明确确认范围');
        const candidates=checked.map(image_id=>({image_id,candidate_digest:miningPreview?.items.find(row=>row.image_id===image_id)?.candidate_digest}));
        const result=await post(`${base}/hard-sample-mining/${encodeURIComponent(miningTaskId)}/adopt`,{confirmed:true,candidates});
        if(!live())return;version.supplement_data_candidate_set=result.candidate_set;reviewMessage='已冻结原Candidate Set；尚未创建训练任务';
      }else if(action==='confirm-decision'){
        const decision=version.iteration_decision||{},kind={needs_data:'supplement_data',continue_training:'continue_training',ready_for_business_validation:'business_validation',review_required:'manual_review'}[decision.decision];
        if(!kind||algorithm.current_version_id!==model.version_id||decision.automatic_execution!==false||decision.requires_confirmation!==true)throw new Error('当前建议不具备确认条件');
        const result=await post(`${base}/iteration-actions/confirm`,{decision_id:decision.decision_id,action:kind});
        if(!live())return;version.confirmed_iteration_action=result.action;reviewMessage='已确认原持久化建议；不会自动创建训练任务';
      }else if(action==='open-training'||action==='resume-decision'){
        const result=await request(`/api/v12/projects/${encodeURIComponent(pid)}/algorithms/${encodeURIComponent(model.algorithm_id)}`,controller?.signal);
        if(!live())return;const latest=result.algorithm||result,latestVersion=latest.versions?.find(row=>row.id===model.version_id);
        if(latest.current_version_id!==model.version_id||latestVersion?.evaluation?.evaluation_id!==version.evaluation?.evaluation_id)throw new Error('当前版本或评测已变化，请刷新后再打开迭代流程');
        state.algorithms=[...(state.algorithms||[]).filter(row=>row.id!==latest.id),latest];
        if(action==='resume-decision'){await window.resumeConfirmedIterationAction429?.(model.algorithm_id,model.version_id);return;}
        const candidateSet=latestVersion.supplement_data_candidate_set;
        if(!candidateSet?.candidate_set_id||candidateSet.candidate_set_id!==version.supplement_data_candidate_set?.candidate_set_id)throw new Error('Candidate Set 已变化，请重新核验');
        if(document.querySelector('#modal:not(.hidden)'))throw new Error('请先关闭当前弹窗，再打开训练草稿');
        state.trainingIterationAction=null;
        await window.startAlgorithmTraining429?.(model.algorithm_id);
        const create=document.querySelector('.train429-create');
        if(!live()||!create||create.dataset.algorithmId!==model.algorithm_id)return;
        const draft=state.trainingDraft||{};
        window.TrainingDraftRuntime?.setMaterialIds?.([...new Set([...(draft.materialIds||[]),...(candidateSet.material_ids||[])])]);
        const banner=document.createElement('div');banner.className='alert soft';banner.textContent=`已预填 ${candidateSet.material_ids?.length||0} 张已审核候选 · 只有点击开始训练才会提交`;create.prepend(banner);return;
      }
      if(live())render();
    }catch(cause){if(live()&&cause.name!=='AbortError'){reviewMessage=String(cause.message||cause);render();}}
    finally{busy=false;if(button.isConnected){button.disabled=false;button.textContent=label;}}
  }
  function mount(){const view=document.getElementById('view');if(!view)return;if(!root())view.innerHTML='<div class="advanced-evaluation" data-advanced-evaluation></div>';render();void load({refreshModels:project!==currentProject()||!models.length});}
  return {mount,deactivate};
}
