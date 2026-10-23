import {eligibleScenarioModels,latestScenarioModel,evaluationTruth,scenarioMetric,visibleEvidenceBoxes,sampleIssueKinds,sampleEvidenceDiagnostics,sameFrozenSample} from './scenario-evaluation.js?v=20261022a';
import {withRequestDeadline} from './api.js?v=20261021s';

// The original v64 presentation owner, relocated from app.js. Tasks, polling,
// GT, reports and durable batches remain with their existing platform owners.
export function installQualityDetectionWorkbench({getState,api,toast,modal,closeModal,esc}) {
  const state=getState();
  const IMAGE_RE64=/\.(?:jpe?g|png|bmp|webp|gif|tiff?)$/i;
  const REVIEW_NAMES64={correct:'正确',missed:'漏检',false_positive:'误检',box_inaccurate:'框不准',wrong_class:'类别错误'};
  const escAttr64=value=>esc(String(value??''));

  let reportSequence=0,reportController=null,reportLoading=false,reportError='',reportVersion=null,reportModel=null;
  let mountedProject='',historySequence=0,batchOpenSequence=0;
  let comparisonSequence=0,comparisonController=null,comparison={};
  let matrixCell=null,curveClass='',classPage=0;
  const reportViews=()=>window.PlatformCore?.reports;
  let displayMode='accuracy',selectedIndex=0,listMode='grid',zoom=1,selectedBox=null;
  let classFilter='',confidence=.25,issueFilter='',showPred=true,showGT=true;
  function detectionModels64(){return eligibleScenarioModels(state.scenarioTestModels||[]);}
  function modelGroup64(model){return `算法 · ${(state.algorithms||[]).find(row=>String(row.id)===String(model.algorithm_id))?.name||model.algorithm_name||model.algorithm_id}`;}
  const modelIdentity64=model=>model?`${model.algorithm_id}:${model.version_id}:${model.training_task_id}:${model.model_sha256}`:'';
  function selectedModel64(side='A') {const value=document.getElementById(`benchModel${side}`)?.value;if(value==null||value==='')return null;const model=(state.scenarioTestModels||[])[Number(value)];return detectionModels64().includes(model)?model:null;}
  function defaultModelIndex64(side='A'){
    const rows=detectionModels64(),algorithmId=document.getElementById(`benchAlgorithm${side}`)?.value||rows[0]?.algorithm_id;
    const model=latestScenarioModel(rows,algorithmId);return (state.scenarioTestModels||[]).indexOf(model);
  }
  function modelOptions64(query='',selected=-1,algorithmId=''){
    const q=String(query).toLowerCase(),group=algorithmId||detectionModels64()[0]?.algorithm_id;
    const rows=detectionModels64().filter(row=>String(row.algorithm_id)===String(group));
    return rows.map(model=>({model,index:(state.scenarioTestModels||[]).indexOf(model)})).filter(({model})=>!q||`${modelGroup64(model)} ${model.version_name||model.label}`.toLowerCase().includes(q))
      .sort((a,b)=>String(b.model.finished_at||b.model.created_at||'').localeCompare(String(a.model.finished_at||a.model.created_at||'')))
      .map(({model,index})=>`<option value="${index}" ${index===Number(selected)?'selected':''}>${esc(model.version_name||model.version_id)}${model===latestScenarioModel(rows,group)?' · 最新有效版本':''}</option>`).join('')||'<option value="">暂无有效成功训练版本</option>';
  }
  function algorithmOptions64(current=''){
    const unique=new Map();for(const model of detectionModels64())if(!unique.has(model.algorithm_id))unique.set(model.algorithm_id,modelGroup64(model).replace(/^算法 · /,''));
    return [...unique].map(([id,name])=>`<option value="${esc(id)}" ${String(id)===String(current)?'selected':''}>${esc(name)}</option>`).join('')||'<option value="">暂无合格算法</option>';
  }
  function modelBrowser64(side,title){
    const model=detectionModels64()[0],index=defaultModelIndex64(side);
    return `<section class="bench64-model-card" data-model-side="${side}"><b>${esc(title)}</b><div class="scn-model-fields"><label>算法<select id="benchAlgorithm${side}" class="select" onchange="scenarioSelectAlgorithm64('${side}')">${algorithmOptions64(model?.algorithm_id)}</select></label><label>成功训练版本<select id="benchModel${side}" class="select" onchange="scenarioSelectVersion64('${side}')">${modelOptions64('',index,model?.algorithm_id)}</select></label></div></section>`;
  }
  window.scenarioSelectAlgorithm64=function(side){
    const select=document.getElementById(`benchModel${side}`);if(select)select.innerHTML=modelOptions64('',defaultModelIndex64(side),document.getElementById(`benchAlgorithm${side}`)?.value);
    window.scenarioSelectVersion64(side);
  };
  window.scenarioSelectVersion64=function(side){
    const select=document.getElementById(`benchModel${side}`),model=selectedModel64(side);
    if(select)select.dataset.modelIdentity=model?`${model.algorithm_id}:${model.version_id}`:'';
    if(side==='A'){reportVersion=null;reportModel=null;selectedIndex=0;void loadScenarioReport64();}else void loadScenarioComparison64();
  };
  async function loadScenarioReport64(){
    reportController?.abort();comparisonController?.abort();comparisonSequence++;comparison={};matrixCell=null;curveClass='';classPage=0;const controller=new AbortController();reportController=controller;
    const sequence=++reportSequence,project=String(pid()),selected=selectedModel64('A');
    reportLoading=false;reportError='';reportVersion=null;reportModel=null;
    if(!selected){renderScenarioAccuracy64();return;}
    reportLoading=true;renderScenarioAccuracy64();
    try{
      const result=await withRequestDeadline(signal=>api(`/api/v12/projects/${project}/algorithms/${encodeURIComponent(selected.algorithm_id)}`,{signal}),{signal:controller.signal,label:'独立评测报告'});
      if(sequence!==reportSequence||String(pid())!==project||controller.signal.aborted||!document.querySelector('.scenario-workbench'))return;
      const algorithm=result.algorithm||result;
      if(String(algorithm.id)!==String(selected.algorithm_id))throw new Error('评测算法身份不一致');
      state.algorithms=(state.algorithms||[]).map(row=>String(row.id)===String(algorithm.id)?algorithm:row);
      const versions=Array.isArray(algorithm.versions)?algorithm.versions:[];
      // Prefer the selected version. If it has no credible report, label the
      // latest available report explicitly; never attribute it to the new model.
      const candidates=versions.map(version=>({version,model:detectionModels64().find(m=>m.algorithm_id===selected.algorithm_id&&m.version_id===version.id)}))
        .filter(row=>row.model&&evaluationTruth(row.version.evaluation,row.model).trusted)
        .sort((a,b)=>String(b.version.evaluation.finished_at||'').localeCompare(String(a.version.evaluation.finished_at||'')));
      const chosen=candidates.find(row=>row.version.id===selected.version_id)||candidates[0];
      if(chosen){reportVersion=chosen.version;reportModel=chosen.model;}
    }catch(error){if(error.name!=='AbortError'&&sequence===reportSequence)reportError=String(error.message||error);}
    finally{if(sequence===reportSequence&&String(pid())===project){reportLoading=false;renderScenarioAccuracy64();void loadScenarioComparison64();}}
  }
  window.retryScenarioReport64=()=>loadScenarioReport64();
  function renderScenarioAccuracy64(){
    const root=document.getElementById('scenarioAccuracy64');if(!root)return;
    reportViews()?.disposeReportViews?.(root);
    if(reportLoading){root.innerHTML='<div class="scn-empty" role="status"><i class="loading-spinner"></i><b>正在读取可信独立评测…</b></div>';return;}
    if(reportError){root.innerHTML=`<div class="scn-empty" role="alert"><b>评测报告读取失败</b><p>${esc(reportError)}</p><button class="btn" onclick="retryScenarioReport64()">重试</button></div>`;return;}
    if(!reportVersion){root.innerHTML='<div class="scn-empty"><b>尚未进行独立评测</b><p>当前算法没有可验证的独立测试集报告。快速图片检测可查看预测，不代表准确率。</p><button class="btn primary" onclick="setScenarioMode64(\'quick\')">快速图片检测</button></div>';return;}
    const e=reportVersion.evaluation,m=e.metrics||{},rows=e.per_class||[],covered=rows.filter(row=>Number(row.ground_truth_count)>0),sum=key=>rows.length&&rows.every(row=>Number.isFinite(row[key]))?rows.reduce((n,row)=>n+row[key],0):null;
    const f1=covered.length&&covered.every(row=>Number.isFinite(row.precision)&&Number.isFinite(row.recall))?covered.reduce((n,row)=>n+(row.precision+row.recall?2*row.precision*row.recall/(row.precision+row.recall):0),0)/covered.length:null;
    const scope=e.benchmark_scope||{},selected=selectedModel64('A');
    root.innerHTML=`<header class="scn-report-head"><div><h3>可信独立测试集评测 · ${esc(reportVersion.version_name||reportVersion.id)}</h3><p>${reportModel.version_id!==selected?.version_id?'当前选择版本尚无可信报告；以下明确展示该算法最近可信报告。':'指标来自当前版本的冻结独立测试集。'}</p></div><button class="btn" onclick="openVersionEvaluation429('${esc(reportModel.algorithm_id)}','${esc(reportModel.version_id)}')">完整独立评测报告</button></header><div class="scn-metrics">${[['Precision',scenarioMetric(m.precision)],['Recall',scenarioMetric(m.recall)],['mAP50',scenarioMetric(m.map50)],['mAP50-95',scenarioMetric(m.map50_95)],['F1（类别宏平均）',scenarioMetric(f1)],['TP / FP / FN',[sum('true_positive'),sum('false_positive'),sum('false_negative')].map(n=>n===null?'未记录':n).join(' / ')]].map(([label,value])=>`<div><span>${label}</span><strong>${value}</strong></div>`).join('')}</div><div class="scn-provenance"><span>测试图片 ${Number.isFinite(e.image_count)?e.image_count:'未记录'}</span><span>评测时间 ${esc(e.finished_at||'未记录')}</span><span>基准 ${esc(scope.scope_id.slice(0,12))}</span><span>正式 GT ${esc(scope.ground_truth_digest.slice(0,12))}</span><span>冻结输入已核验</span></div><details class="scn-trust"><summary>评测可信度与训练 / 验证 / Test 隔离依据</summary><p>测试来源 Snapshot：${esc(e.snapshot_id)} · 数据版本：${esc(e.dataset_revision_id)} · 计算协议：${esc(e.evaluation_protocol_id)}</p><p>冻结训练输入政策：${esc(scope.training_input_policy)}。上述指标仅对应本次 Test；不以验证集或快速检测结果代替。尚未证明的同源、近重复或相邻帧泄漏不能据高分排除。</p>${reportViews()?.metricCredibilityHtml?.(reportVersion.metric_credibility)||''}</details><div id="scenarioComparison64" role="status"></div><div id="scenarioEvidence64"></div><details id="scenarioAnalysis64" class="scn-analysis"><summary>类别指标、混淆矩阵与阈值曲线</summary><div data-scn-analysis-body></div></details>`;
    // Existing reports and frozen image API remain the evidence owners.
    const samples=e.error_samples||[];
    renderEvidenceWorkspace64(document.getElementById('scenarioEvidence64'),samples,'evaluation');
    renderScenarioAnalysis64();renderScenarioComparison64();
  }
  function renderScenarioAnalysis64(){
    const details=document.getElementById('scenarioAnalysis64'),body=details?.querySelector('[data-scn-analysis-body]'),e=reportVersion?.evaluation;if(!body||!e)return;
    reportViews()?.disposeReportViews?.(body);
    const classes=e.per_class||[],pages=Math.max(1,Math.ceil(classes.length/100));classPage=Math.min(classPage,pages-1);
    const curves=(e.confidence_curves||[]).filter(curve=>classes.some(row=>(curve.class_id!=null?row.class_id===curve.class_id:row.label===curve.label)&&Number(row.ground_truth_count)>0));
    if(!curves.some(row=>String(row.class_id??row.label)===curveClass))curveClass=String(curves[0]?.class_id??curves[0]?.label??'');
    const groups=reportViews()?.evaluationChartGroups?.(e,{classId:curveClass})||[];
    const count=value=>Number.isFinite(value)?value:'未记录';
    body.innerHTML=`<p>逐类指标来自冻结独立 Test；未覆盖类不参与宏平均。混淆矩阵采用跨类别置信度优先 IoU≥0.5，与逐类 TP/FP/FN 同类匹配分开解释。</p><div class="table-wrap"><table class="table" data-scn-class-metrics><thead><tr><th>类别 / GT</th><th>Precision</th><th>Recall</th><th>AP50</th><th>AP50-95</th><th>TP / FP / FN</th><th>证据</th></tr></thead><tbody>${classes.slice(classPage*100,(classPage+1)*100).map((row,i)=>{const covered=Number(row.ground_truth_count)>0;return `<tr><td>${esc(row.label)} · ${count(row.ground_truth_count)}${covered?'':' · 未覆盖'}</td>${['precision','recall','map50','map50_95'].map(key=>`<td>${scenarioMetric(row[key],{covered})}</td>`).join('')}<td>${['true_positive','false_positive','false_negative'].map(key=>count(row[key])).join(' / ')}</td><td><button class="btn small" onclick="scenarioShowClassEvidence64(${classPage*100+i})">查看框证据</button></td></tr>`}).join('')||'<tr><td colspan="7">未保存逐类别指标</td></tr>'}</tbody></table></div><div class="row"><button class="btn small" ${classPage===0?'disabled':''} onclick="scenarioAnalysisPage64(-1)">上一页类别</button><span>${classPage+1} / ${pages}</span><button class="btn small" ${classPage+1>=pages?'disabled':''} onclick="scenarioAnalysisPage64(1)">下一页类别</button><label>曲线类别<select class="select" data-scn-curve onchange="scenarioAnalysisClass64(this.value)">${curves.map(row=>`<option value="${esc(row.class_id??row.label)}" ${String(row.class_id??row.label)===curveClass?'selected':''}>${esc(row.label)}</option>`).join('')||'<option>无有GT覆盖的真实曲线</option>'}</select></label></div><div class="scn-analysis-charts">${groups.map(group=>`<section class="report-chart-card"><header><b>${esc(group.title)}</b></header><div class="report-interactive-chart" data-report-chart="${esc(group.key)}" role="img" aria-label="${esc(group.title)}"></div><div data-chart-fallback hidden>交互图表不可用；上方保留正式逐类指标，缺失曲线不补造。</div></section>`).join('')||'<p>历史报告未保存可验证的矩阵或曲线，不能由最终指标推算。</p>'}</div><p>PR为实际阈值采样曲线，非AP积分曲线；Confidence仅显示存在的真实阈值点。矩阵最多显示前20类和背景，点击只筛选已保留的样本；未保留图片不代表没有错误。</p>`;
    const mount=()=>{if(details.open)void reportViews()?.mountEvaluationCharts?.(body,e,{classId:curveClass,onCell:cell=>{matrixCell=cell;issueFilter='';selectedIndex=0;const root=document.getElementById('scenarioEvidence64');renderEvidenceWorkspace64(root,e.error_samples||[],'evaluation');root?.scrollIntoView({block:'start'});}});};
    details.ontoggle=mount;mount();
  }
  window.scenarioAnalysisClass64=value=>{curveClass=String(value);renderScenarioAnalysis64();};
  window.scenarioAnalysisPage64=delta=>{classPage=Math.max(0,classPage+Number(delta));renderScenarioAnalysis64();};
  window.scenarioShowClassEvidence64=index=>{const row=reportVersion?.evaluation?.per_class?.[index];if(!row)return;classFilter=Number.isInteger(row.class_id)?`id:${row.class_id}`:String(row.label);const root=document.getElementById('scenarioEvidence64');renderEvidenceWorkspace64(root,evidenceRows64('evaluation'),'evaluation');root?.scrollIntoView({block:'start'});};
  window.scenarioClearMatrix64=()=>{matrixCell=null;const root=document.getElementById('scenarioEvidence64');renderEvidenceWorkspace64(root,evidenceRows64('evaluation'),'evaluation');};
  const comparisonReasons64={benchmark_scope_mismatch:'冻结测试基准不同',benchmark_evidence_missing:'缺少冻结基准证据',benchmark_input_binding_missing:'测试输入未完成校验',evaluation_protocol_mismatch:'指标计算协议不同',class_identity_ambiguous:'类别身份不兼容',evaluation_missing:'缺少可信评测'};
  function renderScenarioComparison64(){
    const root=document.getElementById('scenarioComparison64');if(!root)return;
    if(!document.querySelector('.scenario-workbench.bench350-comparison')){root.replaceChildren();return;}
    if(comparison.loading){root.innerHTML='<div class="scn-comparison" role="status"><i class="loading-spinner"></i>正在核验同基准版本对比…</div>';return;}
    const result=comparison.result;
    if(!result?.comparable){root.innerHTML=`<div class="scn-comparison"><b>暂不可作准确率提升比较</b><p>${esc(comparison.error||(result?.reason_codes||[]).map(code=>comparisonReasons64[code]||code).join('；')||'请选择同算法另一个有可信独立评测的成功版本。')}</p>${comparison.error?'<button class="btn small" onclick="retryScenarioComparison64()">重试对比核验</button>':''}</div>`;return;}
    const m=result.metrics||{};
    root.innerHTML=`<div class="scn-comparison" data-scn-comparison-result><b>同冻结基准 · A ${esc(reportModel?.version_name||reportModel?.version_id)} 相对 B ${esc(comparison.model?.version_name||comparison.model?.version_id)}</b><div class="scn-comparison-metrics">${[['precision','Precision'],['recall','Recall'],['map50','mAP50'],['map50_95','mAP50-95']].map(([key,label])=>{const value=m[key];return `<span>${label}：${scenarioMetric(value?.before)} → ${scenarioMetric(value?.after)} · ${Number.isFinite(value?.delta)?reportViews().formatPercentagePointDelta(value.delta):'差异未记录'}</span>`}).join('')}</div><p>差异来自服务端同基准/协议/类别映射核验后的正式结果，以百分点（pp）表示；不推算生产准确率或相对提升百分比。</p></div>`;
  }
  async function loadScenarioComparison64(){
    comparisonController?.abort();const controller=new AbortController();comparisonController=controller;const sequence=++comparisonSequence,project=String(pid()),a=selectedModel64('A'),b=selectedModel64('B'),origin=reportVersion;
    comparison={};renderScenarioComparison64();
    const updateEvidence=()=>{const root=document.getElementById('scenarioEvidence64');if(displayMode==='accuracy'&&root&&reportVersion)void renderSelectedEvidence64(root,'evaluation');};
    updateEvidence();
    if(!document.querySelector('.scenario-workbench.bench350-comparison')||!a||!b||!reportVersion)return;
    if(a.algorithm_id!==b.algorithm_id||a.version_id===b.version_id||reportModel?.version_id!==a.version_id){comparison.error=a.algorithm_id!==b.algorithm_id?'严格评测比较仅支持同算法的成功版本；快速检测支持跨算法同图查看。':'请选择两个不同且各有可信报告的成功版本。';renderScenarioComparison64();updateEvidence();return;}
    const version=(state.algorithms||[]).find(row=>row.id===b.algorithm_id)?.versions?.find(row=>row.id===b.version_id);
    if(!evaluationTruth(version?.evaluation,b).trusted){comparison.error='对比版本没有可信独立评测，不能计算提升。';renderScenarioComparison64();updateEvidence();return;}
    comparison={loading:true};renderScenarioComparison64();
    const current=()=>sequence===comparisonSequence&&String(pid())===project&&reportVersion===origin&&modelIdentity64(selectedModel64('A'))===modelIdentity64(a)&&modelIdentity64(selectedModel64('B'))===modelIdentity64(b)&&!controller.signal.aborted&&!!document.querySelector('.scenario-workbench.bench350-comparison');
    try{
      const response=await withRequestDeadline(signal=>api(`/api/v12/projects/${project}/algorithms/${encodeURIComponent(a.algorithm_id)}/versions/${encodeURIComponent(a.version_id)}/evaluation/compare/${encodeURIComponent(b.version_id)}`,{signal}),{signal:controller.signal,label:'同基准版本对比'});
      if(!current())return;const result=response.comparison;
      if(!result||result.source_version_id!==b.version_id||result.current_version_id!==a.version_id)throw new Error('版本对比回执身份不一致');
      comparison={result,model:b,version};
    }catch(error){if(!current())return;comparison={error:String(error.message||error)};}
    if(current()){renderScenarioComparison64();updateEvidence();}
  }
  window.retryScenarioComparison64=()=>loadScenarioComparison64();
  window.setScenarioMode64=function(mode){
    displayMode=mode==='quick'?'quick':'accuracy';
    document.querySelectorAll('[data-scenario-mode]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.scenarioMode===displayMode)));
    for(const [id,visible] of [['scenarioAccuracy64',displayMode==='accuracy'],['scenarioQuick64',displayMode==='quick']]){const node=document.getElementById(id);if(node)node.hidden=!visible;}
    if(displayMode==='accuracy'&&!reportLoading&&!reportVersion&&!reportError)void loadScenarioReport64();
    if(displayMode==='accuracy'&&reportVersion)renderEvidenceWorkspace64(document.getElementById('scenarioEvidence64'),evidenceRows64('evaluation'),'evaluation');
    if(displayMode==='quick'&&batch64())renderEvidenceWorkspace64(document.getElementById('scenarioQuickEvidence64'),evidenceRows64('quick'),'quick');
  };
  let evidenceController=null,evidenceObserver=null;
  const evidenceUrls=new Set();
  function revokeEvidenceUrls64(){evidenceController?.abort();evidenceObserver?.disconnect();evidenceObserver=null;for(const url of evidenceUrls)URL.revokeObjectURL(url);evidenceUrls.clear();}
  function evidenceRows64(kind){return kind==='evaluation'?(reportVersion?.evaluation?.error_samples||[]):(batch64()?.results||[]);}
  function filteredEvidence64(kind){
    return evidenceRows64(kind).map((row,index)=>({row,index})).filter(({row})=>kind!=='evaluation'||((!issueFilter||sampleIssueKinds(row,{evaluation:reportVersion?.evaluation}).includes(issueFilter))&&(!matrixCell||matrixCell.images?.includes(row.image))));
  }
  function thumbnailUrl64(row,kind){
    if(kind==='evaluation'){
      if(!row.image_id||!row.image_content_sha256||!reportModel)return '';
      const query=new URLSearchParams({expected_evaluation_id:reportVersion.evaluation.evaluation_id,expected_image_id:row.image_id,expected_sha256:row.image_content_sha256});
      return `/api/v12/projects/${encodeURIComponent(pid())}/algorithms/${encodeURIComponent(reportModel.algorithm_id)}/versions/${encodeURIComponent(reportModel.version_id)}/evaluation/images/${encodeURIComponent(row.image)}?${query}`;
    }
    if(row.file instanceof File&&!row.previewUrl)row.previewUrl=URL.createObjectURL(row.file);
    return row.previewUrl||row.inputImageUrl||row.a?.r?.input_image_url||row.b?.r?.input_image_url||'';
  }
  function renderEvidenceWorkspace64(root,rows,kind){
    if(!root||(kind==='evaluation'?displayMode!=='accuracy':displayMode!=='quick'))return;
    root.dataset.evidenceKind=kind;
    const choices=filteredEvidence64(kind),pages=Math.max(1,Math.ceil(choices.length/24));
    if(!choices.some(item=>item.index===selectedIndex))selectedIndex=choices[0]?.index||0;
    const selectedPage=Math.max(0,Math.floor(choices.findIndex(item=>item.index===selectedIndex)/24));
    const labels=[...new Set(rows.flatMap(row=>kind==='evaluation'?[...(row.gt_boxes||[]),...(row.pred_boxes||[])]:[...(row.a?.r?.detections||[]),...(row.b?.r?.detections||[])]).map(box=>String(box.label||'')).filter(Boolean))];
    const classOptions=kind==='evaluation'?(reportVersion.evaluation.per_class||[]).map(row=>({value:Number.isInteger(row.class_id)?`id:${row.class_id}`:String(row.label),name:row.label})):labels.map(label=>({value:label,name:label}));
    root.innerHTML=`${kind==='evaluation'?`<div class="scn-evidence-counts">${[['tp','已匹配 TP'],['fp','误检 FP'],['fn','漏检 FN']].map(([key,label])=>`<button class="btn small" aria-pressed="${issueFilter===key}" onclick="scenarioEvidenceFilter64('issue','${key}')">${label}</button>`).join('')}<span>仅筛选已保存证据（最多200图、每层120框），不代表完整测试集。</span>${matrixCell?'<button class="btn small" onclick="scenarioClearMatrix64()">清除矩阵筛选</button>':''}</div>`:''}<div class="scn-evidence-tools"><div class="row"><button class="btn small" onclick="scenarioEvidenceLayout64('grid')" aria-pressed="${listMode==='grid'}">图片网格</button><button class="btn small" onclick="scenarioEvidenceLayout64('list')" aria-pressed="${listMode==='list'}">图片列表</button><label>类别<select class="select" data-scn-class onchange="scenarioEvidenceFilter64('class',this.value)"><option value="">全部类别</option>${classOptions.map(row=>`<option value="${esc(row.value)}" ${row.value===classFilter?'selected':''}>${esc(row.name)}</option>`).join('')}</select></label>${kind==='evaluation'?`<label>问题类型<select class="select" data-scn-issue onchange="scenarioEvidenceFilter64('issue',this.value)">${[['','全部证据'],['tp','已匹配 TP'],['fp','误检'],['fn','漏检'],['wrong_class','类别错误'],['localization','定位待复核'],['low_confidence','低置信度（<0.5）']].map(([value,name])=>`<option value="${value}" ${value===issueFilter?'selected':''}>${name}</option>`).join('')}</select></label>`:''}</div><div class="row"><label><input type="checkbox" ${showPred?'checked':''} onchange="scenarioEvidenceFilter64('pred',this.checked)">预测框</label><label><input type="checkbox" ${showGT?'checked':''} ${kind==='evaluation'?'':'disabled'} onchange="scenarioEvidenceFilter64('gt',this.checked)">正式 GT</label><label>显示阈值<input class="input" data-scn-confidence type="number" value="${confidence}" min="0" max="1" step=".05" onchange="scenarioEvidenceFilter64('confidence',this.value)"></label><button class="btn small" onclick="scenarioEvidenceZoom64(-.25)" aria-label="缩小图片">−</button><button class="btn small" onclick="scenarioEvidenceZoom64(.25)" aria-label="放大图片">＋</button><button class="btn small" onclick="scenarioEvidenceZoom64(0)">适应窗口</button></div></div><div class="scn-inspection"><aside class="scn-queue ${listMode}" aria-label="图片结果队列">${choices.slice(selectedPage*24,(selectedPage+1)*24).map(({row,index})=>`<button class="scn-sample ${index===selectedIndex?'selected':''}" data-scn-sample="${index}" onclick="scenarioSelectSample64(${index})"><span class="scn-thumb" data-scn-thumb="${index}">${thumbnailUrl64(row,kind)?`<img src="${esc(thumbnailUrl64(row,kind))}" loading="lazy" alt="${esc(row.image||row.file?.name||'图片缩略图')}" onerror="this.hidden=true;this.parentElement.dataset.imageError='图片不可用'">`: ''}${kind==='evaluation'?`<b>${Number(row.fp_count||0)} FP · ${Number(row.fn_count||0)} FN</b>`:`<b>${({done:'完成',failed:'失败',running:'检测中',pending:'待提交',partial:'已停止后续',not_submitted:'未提交'})[row.status]||row.status}</b>`}</span><strong title="${esc(row.image||row.file?.name||'')}">${esc(row.image||row.file?.webkitRelativePath||row.file?.name||'图片')}</strong></button>`).join('')||'<div class="scn-empty">暂无匹配图片；未记录的错误类型不能由前端猜测。</div>'}<div class="scn-pagination"><button class="btn small" ${selectedPage===0?'disabled':''} onclick="scenarioEvidencePage64(-1)">上一页</button><span>${selectedPage+1}/${pages}</span><button class="btn small" ${selectedPage+1>=pages?'disabled':''} onclick="scenarioEvidencePage64(1)">下一页</button></div></aside><section class="scn-image-workspace"><div class="scn-image-navigation"><button class="btn small" ${choices.findIndex(item=>item.index===selectedIndex)<=0?'disabled':''} onclick="scenarioStepSample64(-1)">上一张</button><span>${choices.length?choices.findIndex(item=>item.index===selectedIndex)+1:0} / ${choices.length}</span><button class="btn small" ${choices.findIndex(item=>item.index===selectedIndex)>=choices.length-1?'disabled':''} onclick="scenarioStepSample64(1)">下一张</button></div><div class="scn-stages" data-scn-stages></div></section><aside class="scn-box-details" data-scn-box-details><h4>检测框与复核</h4><p>选择图片后查看真实框证据。</p></aside></div>`;
    renderSelectedEvidence64(root,kind);
  }
  function activeEvidence64(){return document.querySelector(displayMode==='accuracy'?'#scenarioEvidence64':'#scenarioQuickEvidence64');}
  window.scenarioSelectSample64=function(index){selectedIndex=Number(index);selectedBox=null;zoom=1;const root=activeEvidence64();if(root)renderEvidenceWorkspace64(root,evidenceRows64(root.dataset.evidenceKind),root.dataset.evidenceKind);};
  window.scenarioStepSample64=function(delta){const root=activeEvidence64();if(!root)return;const choices=filteredEvidence64(root.dataset.evidenceKind),i=choices.findIndex(row=>row.index===selectedIndex),next=choices[i+delta];if(next)window.scenarioSelectSample64(next.index);};
  window.scenarioEvidencePage64=function(delta){const root=activeEvidence64();if(!root)return;const choices=filteredEvidence64(root.dataset.evidenceKind),i=choices.findIndex(row=>row.index===selectedIndex),next=choices[(Math.floor(i/24)+delta)*24];if(next)window.scenarioSelectSample64(next.index);};
  window.scenarioEvidenceLayout64=function(mode){listMode=mode==='list'?'list':'grid';const root=activeEvidence64();if(root)renderEvidenceWorkspace64(root,evidenceRows64(root.dataset.evidenceKind),root.dataset.evidenceKind);};
  window.scenarioEvidenceFilter64=function(key,value){
    if(key==='class')classFilter=String(value);if(key==='confidence')confidence=Math.max(0,Math.min(1,Number(value)||0));
    if(key==='issue'){issueFilter=String(value);matrixCell=null;selectedIndex=0;}if(key==='pred')showPred=!!value;if(key==='gt')showGT=!!value;
    const root=activeEvidence64();if(root)renderEvidenceWorkspace64(root,evidenceRows64(root.dataset.evidenceKind),root.dataset.evidenceKind);
  };
  window.scenarioEvidenceZoom64=function(delta){zoom=delta===0?1:Math.max(.25,Math.min(4,zoom+delta));const root=activeEvidence64();root?.querySelectorAll('.scn-stage figure').forEach(fitStage64);};
  function fitStage64(figure){
    if(!figure?.isConnected)return;const image=figure.querySelector('img');if(!image?.naturalWidth)return;
    const media=figure.parentElement,w=Math.max(40,media.clientWidth-24),h=Math.max(100,media.clientHeight-24);
    const scale=Math.min(w/image.naturalWidth,h/image.naturalHeight)*zoom;
    figure.style.width=`${image.naturalWidth*scale}px`;figure.style.height=`${image.naturalHeight*scale}px`;
  }
  function drawStageBoxes64(figure,boxes,width,height){
    const svg=figure.querySelector('svg');if(!svg)return;
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
    const fontSize=Math.max(width/65,12*width/Math.max(1,figure.clientWidth));
    svg.innerHTML=boxes.map((row,index)=>({row,index})).filter(({row})=>(row.layer==='gt'?showGT:showPred)).map(({row,index})=>{
      const box=row.box||[row.x1,row.y1,row.x2,row.y2],color=row.layer==='gt'?'#16a34a':'#2563eb';
      if(box.some((n,i)=>n<0||n>(i%2?height:width)))return '';
      return `<g role="button" tabindex="0" data-box-index="${index}" aria-label="${esc(row.label)} ${row.layer==='gt'?'正式GT':'预测'}"><rect x="${box[0]}" y="${box[1]}" width="${box[2]-box[0]}" height="${box[3]-box[1]}" fill="${color}" fill-opacity=".05" stroke="${color}" stroke-width="${Math.max(1,width/500)}" vector-effect="non-scaling-stroke"/><text x="${box[0]}" y="${Math.max(fontSize,box[1]-fontSize/3)}" fill="${color}" font-size="${fontSize}">${esc(row.label)}${Number.isFinite(row.confidence)?` ${(row.confidence*100).toFixed(1)}%`:''}</text></g>`;
    }).join('');
    svg.removeAttribute('hidden');
    const activate=event=>{const target=event.target.closest('[data-box-index]');if(!target||event.type==='keydown'&&!['Enter',' '].includes(event.key))return;if(event.type==='keydown')event.preventDefault();const root=activeEvidence64(),detail=root?.querySelector(`[data-scn-box="${figure.dataset.side}:${target.dataset.boxIndex}"]`);root?.querySelectorAll('[data-scn-box]').forEach(node=>node.classList.toggle('selected',node===detail));detail?.scrollIntoView({block:'nearest'});};
    svg.onclick=activate;svg.onkeydown=activate;
  }
  async function renderSelectedEvidence64(root,kind){
    revokeEvidenceUrls64();const controller=new AbortController();evidenceController=controller;
    const row=evidenceRows64(kind)[selectedIndex],host=root.querySelector('[data-scn-stages]'),aside=root.querySelector('[data-scn-box-details]');if(!row||!host)return;
    const project=String(pid()),current=()=>root.isConnected&&String(pid())===project&&!controller.signal.aborted;
    const panels=kind==='evaluation'?[{side:'A',title:reportVersion.version_name||reportVersion.id,sample:row,model:reportModel,evaluation:reportVersion.evaluation}]:[['A',row.a],['B',row.b]].filter(([,value])=>value).map(([side,value])=>({side,title:resultName64(value,side),sample:{pred_boxes:value.r?.detections||[]},url:row.inputImageUrl||value.r?.input_image_url||row.previewUrl||'',value}));
    if(kind==='evaluation'&&comparison.result?.comparable&&comparison.version){const other=(comparison.version.evaluation.error_samples||[]).find(sample=>sameFrozenSample(row,sample));if(other)panels.push({side:'B',title:comparison.version.version_name||comparison.version.id,sample:other,model:comparison.model,evaluation:comparison.version.evaluation});}
    if(!panels.length){host.innerHTML=`<div class="scn-empty" role="status"><b>${row.status==='failed'?'检测失败':row.status==='running'?'正在处理图片':row.status==='unknown'?'创建结果待核验':'等待检测结果'}</b><p>${esc(row.error||'真实任务完成后会直接显示首张图片。')}</p></div>`;return;}
    host.classList.toggle('paired',panels.length>1);host.innerHTML=panels.map(panel=>`<section><header>${esc(panel.side)} · ${esc(panel.title)}</header><div class="scn-stage"><p role="status">正在读取图片…</p><figure data-side="${panel.side}" hidden><img alt="${esc(row.image||row.file?.name||'检测原图')}" decoding="async"><svg hidden aria-label="预测与正式GT检测框" preserveAspectRatio="none"></svg></figure><button class="btn small" data-scn-image-retry hidden onclick="scenarioSelectSample64(${selectedIndex})">重试图片</button></div></section>`).join('');
    let detail='<h4>检测框与复核</h4>';
    for(const panel of panels){
      const boxFilter=classFilter.startsWith('id:')?{classId:Number(classFilter.slice(3))}:{label:classFilter};
      const gt=visibleEvidenceBoxes(panel.sample.gt_boxes||[],boxFilter).map(box=>({...box,layer:'gt'}));
      const pred=visibleEvidenceBoxes(panel.sample.pred_boxes||[],{...boxFilter,confidence,prediction:true}).map(box=>({...box,layer:'pred'}));
      panel.boxes=[...gt,...pred];
      detail+=`<h5>${esc(panel.side)} · 正式 GT ${kind==='evaluation'?(panel.sample.gt_boxes?.length??'未记录'):'不可用'} / 预测 ${panel.sample.pred_boxes?.length??'未记录'}</h5>${panel.boxes.map((box,index)=>`<button class="scn-box-row" data-scn-box="${panel.side}:${index}"><b>${box.layer==='gt'?'GT':'预测'} · ${esc(box.label)}</b><span>${Number.isFinite(box.confidence)?`置信度 ${(box.confidence*100).toFixed(1)}%`:'未记录置信度'}${kind==='evaluation'?` · ${typeof box.matched==='boolean'?(box.matched?'已匹配':box.layer==='gt'?'漏检':'误检'):'未记录匹配关系'}`:''}</span><small>[${(box.box||[box.x1,box.y1,box.x2,box.y2]).map(n=>Number(n).toFixed(1)).join(', ')}]</small></button>`).join('')||'<p>暂无符合筛选条件的真实框。</p>'}`;
    }
    if(kind==='evaluation')detail+=`<p>冻结独立测试证据只读。显示阈值只过滤可视框，不重算正式指标；历史截断框不能补造。定位待复核是同类未匹配框的0&lt;IoU&lt;0.5几何线索，并非正式错误指标。低置信度仅指真实预测&lt;0.5。</p>${comparison.result?.comparable&&panels.length<2?'<p class="scn-comparison-missing">对比版本未保留本图同身份框证据，不能用空框推断正确检出。</p>':''}`;
    else detail+=`<div class="scn-human-review"><b>人工主观复核 · 与正式指标分开</b><span id="benchReviewStatus64">${esc(REVIEW_NAMES64[row.review]||'尚未核验')}</span>${[['A',row.a],['B',row.b]].filter(([,value])=>canSubmitBenchFeedback64(value)).map(([side])=>`<button class="btn small" onclick="openBenchFeedback64(${selectedIndex},'${side}')">${side} · 提交抽检反馈</button>`).join('')}${Object.entries(REVIEW_NAMES64).map(([key,label])=>`<button class="btn small" onclick="markBenchReview64(${selectedIndex},'${key}')">${label}</button>`).join('')}</div>`;
    if(kind==='evaluation'){
      detail+=panels.map(panel=>`<div class="scn-match-evidence"><b>${esc(panel.side)} · 正式匹配与辅助诊断</b>${panel.boxes.map(box=>`<p>${esc(box.label)} · ${Number.isFinite(box.matched_iou)?`IoU ${box.matched_iou.toFixed(3)}`:'IoU 未记录'} · ${esc((box.diagnostic_tags||[]).map(tag=>({wrong_class:'类别错误线索',localization:'定位偏差线索',duplicate:'重复检测线索',low_confidence:'低置信度'}[tag]||tag)).join(' / ')||'无额外诊断')} ${Number.isInteger(box.target_index)?`GT #${box.target_index+1}`:''}</p>`).join('')||'<p>本图未保留完整框证据，不能以空框推断正确或漏检。</p>'}</div>`).join('');
    }
    if(kind==='evaluation')for(const panel of panels){
      const clues=sampleEvidenceDiagnostics(panel.sample,{evaluation:panel.evaluation}).localizationCandidates;
      if(clues.length)detail+=`<div class="scn-match-evidence"><b>${esc(panel.side)} · 定位几何候选（不改变正式匹配）</b>${clues.map(clue=>`<p>预测 #${clue.predictionIndex+1} → GT #${clue.groundTruthIndex+1} · IoU ${clue.iou.toFixed(3)}</p>`).join('')}</div>`;
    }
    aside.innerHTML=detail;
    aside.onclick=event=>{const button=event.target.closest('[data-scn-box]');if(!button)return;const [side,index]=button.dataset.scnBox.split(':'),target=host.querySelector(`figure[data-side="${side}"] svg [data-box-index="${index}"]`);aside.querySelectorAll('[data-scn-box]').forEach(node=>node.classList.toggle('selected',node===button));target?.focus();};
    const scrollPanels=[...host.querySelectorAll('.scn-stage')];let syncing=false;
    scrollPanels.forEach(source=>source.addEventListener('scroll',()=>{if(syncing)return;syncing=true;for(const target of scrollPanels)if(target!==source){target.scrollLeft=source.scrollLeft/Math.max(1,source.scrollWidth-source.clientWidth)*(target.scrollWidth-target.clientWidth);target.scrollTop=source.scrollTop/Math.max(1,source.scrollHeight-source.clientHeight)*(target.scrollHeight-target.clientHeight);}syncing=false;},{signal:controller.signal}));
    for(const panel of panels){
      const figure=host.querySelector(`figure[data-side="${panel.side}"]`),image=figure.querySelector('img'),message=figure.parentElement.querySelector('p'),retry=figure.parentElement.querySelector('[data-scn-image-retry]');
      try{
        let url=panel.url;
        if(kind==='evaluation'){
          const e=panel.evaluation,sample=panel.sample;
          if(!sample.image_id||!sample.image_content_sha256)throw new Error('历史图片缺少可验证身份，不能加载同名图片');
          const query=new URLSearchParams({expected_evaluation_id:e.evaluation_id,expected_image_id:sample.image_id,expected_sha256:sample.image_content_sha256});
          const path=`/api/v12/projects/${project}/algorithms/${encodeURIComponent(panel.model.algorithm_id)}/versions/${encodeURIComponent(panel.model.version_id)}/evaluation/images/${encodeURIComponent(sample.image)}?${query}`;
          const blob=await withRequestDeadline(async signal=>{const response=await window.fetch(path,{signal,headers:{Accept:'image/*'}});if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail?.message||body.detail||`冻结图片读取失败 HTTP ${response.status}`);}return response.blob();},{signal:controller.signal,label:'冻结图片证据'});
          if(!current())return;url=URL.createObjectURL(blob);evidenceUrls.add(url);
        }else if(!url&&row.file instanceof File){url=URL.createObjectURL(row.file);evidenceUrls.add(url);}
        if(!url)throw new Error('原图已不可访问；请核验历史证据');
        image.onload=()=>{
          if(!current())return;
          const width=image.naturalWidth,height=image.naturalHeight;
          if(kind==='evaluation'&&(width!==Number(panel.sample.image_width)||height!==Number(panel.sample.image_height))){message.textContent='图片尺寸与冻结框证据不一致，已停止展示';retry.hidden=false;return;}
          figure.hidden=false;message.hidden=true;fitStage64(figure);drawStageBoxes64(figure,panel.boxes,width,height);
          const thumb=root.querySelector(`[data-scn-thumb="${selectedIndex}"]`);if(thumb&&!thumb.querySelector('img')){const tiny=image.cloneNode();tiny.removeAttribute('hidden');tiny.alt='当前图片缩略图';thumb.prepend(tiny);}
        };
        image.onerror=()=>{if(current()){figure.hidden=true;message.hidden=false;message.textContent='图片加载失败，检测框已隐藏';retry.hidden=false;}};image.src=url;
      }catch(error){if(current()){message.textContent=String(error.message||error);retry.hidden=false;}}
    }
    if(typeof ResizeObserver!=='undefined'){evidenceObserver=new ResizeObserver(()=>host.querySelectorAll('figure:not([hidden])').forEach(fitStage64));host.querySelectorAll('.scn-stage').forEach(node=>evidenceObserver.observe(node));}
  }
  function fileKey64(file){return [file?.name,file?.size,file?.lastModified,file?.webkitRelativePath||''].join('|')}
  function validImage64(file){return /^image\//i.test(String(file?.type||''))||IMAGE_RE64.test(String(file?.name||''))}
  function batch64(){return state.benchBatch64||null}
  function resultName64(result,fallback){return result?.m?.label||result?.m?.model_name||result?.m?.path||fallback}

  window.addBenchFiles64=function(input){
    const incoming=[...(input?.files||[])],valid=incoming.filter(validImage64),invalid=incoming.length-valid.length,current=state.benchFiles64||[],seen=new Set(current.map(fileKey64));
    for(const file of valid){const key=fileKey64(file);if(!seen.has(key)){current.push(file);seen.add(key)}}
    state.benchFiles64=current;
    if(input)input.value='';
    renderBenchFileQueue64();
    if(invalid)toast(`已忽略 ${invalid} 个非图片文件`);
  };
  window.clearBenchFiles64=function(){
    if(state.benchBatch64?.running||state.benchBatch64?.outcomeUncertain)return toast('检测进行中或创建结果未知，请先等待完成或核验原批次');
    revokeEvidenceUrls64();
    for(const row of state.benchBatch64?.results||[]){if(row.previewUrl)URL.revokeObjectURL(row.previewUrl)}
    state.benchFiles64=[];state.benchBatch64=null;renderBenchFileQueue64();renderBenchBatch64();
  };
  window.removeBenchFile64=function(key){
    state.benchFiles64=(state.benchFiles64||[]).filter(file=>fileKey64(file)!==String(key));
    renderBenchFileQueue64();
  };
  window.previewBenchFile64=function(index=0){
    const file=(state.benchFiles64||[])[Number(index)];if(!file)return;
    const box=document.getElementById('benchPreview64');if(!box)return;
    const url=URL.createObjectURL(file),previous=box.dataset.objectUrl;if(previous)URL.revokeObjectURL(previous);
    box.dataset.objectUrl=url;box.innerHTML=`<img src="${url}" alt=""><span>${esc(file.webkitRelativePath||file.name)}</span>`;
  };
  window.renderBenchFileQueue64=function(){
    const files=state.benchFiles64||[],count=document.getElementById('benchFileCount64'),list=document.getElementById('benchFileList64');
    if(count)count.textContent=files.length?`已选择 ${files.length} 张图片`:'尚未选择图片';
    if(list)list.innerHTML=files.slice(0,80).map((file,index)=>`<button type="button" class="bench64-file-chip" onclick="previewBenchFile64(${index})"><span>${esc(file.webkitRelativePath||file.name)}</span><em>${(Number(file.size||0)/1024/1024).toFixed(2)} MB</em><i onclick="event.stopPropagation();removeBenchFile64('${escAttr64(fileKey64(file))}')">×</i></button>`).join('')+(files.length>80?`<div class="item-sub">另有 ${files.length-80} 张图片已加入本次检测。</div>`:'');
    if(files.length)window.previewBenchFile64(0);else{const box=document.getElementById('benchPreview64');if(box)box.innerHTML='<span>选择图片后在这里预览</span>'}
  };

  function summary64(){
    const run=batch64(),box=document.getElementById('benchBatchSummary64');if(!box)return;
    if(!run){box.innerHTML='<div class="bench64-empty"><b>暂无本次检测结果</b><span>选择图片后开始检测，批量结果会保留在当前页面。</span></div>';return}
    const percent=run.total?Math.round(run.completed/run.total*100):0;
    box.innerHTML=`<div class="bench64-summary-grid"><div><span>本次图片</span><b>${run.total}</b></div><div><span>已完成</span><b>${run.completed}</b></div><div><span>成功</span><b>${run.success}</b></div><div><span>失败</span><b>${run.failed}</b></div><div><span>进度</span><b>${percent}%</b></div></div><div class="bench64-runbar"><i style="transform:scaleX(${(percent/100).toFixed(4)})"></i></div><div class="row between"><span class="item-sub">${run.outcomeUncertain?'创建结果待核验；服务端可能已接收，请查询原批次，勿重复创建。':run.running?'正在按图片顺序执行真实模型推理。':run.cancelled?'已停止后续图片检测，已提交任务仍由任务中心管理。':'本次检测已结束。'}</span>${run.running?'<button class="btn danger small" onclick="stopBenchBatch64()">停止后续检测</button>':''}${run.outcomeUncertain?`<button class="btn" onclick="openDetectionBatch64('${esc(run.id)}')">查询本次批次结果</button>`:''}</div><p class="scn-run-status" role="status">${esc(run.progressMessage||'')}</p>`;
  }
  function updateScenarioProgress64(run,task,project){
    if(String(pid())!==project||state.benchBatch64!==run)return;
    const view=window.PlatformCore.deployment.deploymentTaskView(task);run.progressMessage=[view.statusText,view.phase,view.runtimeText].filter(Boolean).join(' · ');
    const node=document.querySelector('.scn-run-status');if(node)node.textContent=run.progressMessage;
  }
  function rowHtml64(row,index){
    const aCount=Number(row.a?.r?.detections?.length||0),bCount=Number(row.b?.r?.detections?.length||0),review=row.review?REVIEW_NAMES64[row.review]||row.review:'未核验';
    const status=row.status==='done'?'完成':row.status==='failed'?'失败':row.status==='running'?'检测中':row.status==='unknown'?'创建结果待核验':row.status==='partial'?'A已完成，B未提交':row.status==='not_submitted'?'未提交':'等待';
    return `<div class="bench64-result-row ${row.status}" data-bench-result-id="${escAttr64(row.id)}"><div class="bench64-result-main"><b>${esc(row.file.webkitRelativePath||row.file.name)}</b><span>${status}${row.error?' · '+esc(row.error):''}</span></div><div><span>A 模型</span><b>${row.a?aCount+' 个目标':'—'}</b></div><div><span>B 模型</span><b>${row.b?bCount+' 个目标':'—'}</b></div><div><span>人工核验</span><b>${esc(review)}</b></div><button class="btn mini" ${row.status==='done'?'':'disabled'} onclick="openBenchResult64(${index})">查看详情</button></div>`;
  }
  window.renderBenchBatch64=function(){
    summary64();
    const run=batch64(),list=document.getElementById('benchBatchList64');
    if(!list)return;
    if(!run){list.innerHTML='';const evidence=document.getElementById('scenarioQuickEvidence64');if(evidence)evidence.innerHTML='<div class="scn-empty">选择图片后开始检测，结果将直接显示在这里。</div>';return}
    list.innerHTML=run.results.map(rowHtml64).join('');
    renderEvidenceWorkspace64(document.getElementById('scenarioQuickEvidence64'),run.results,'quick');
  };
  function patchBenchRow64(index){
    summary64();
    const run=batch64(),list=document.getElementById('benchBatchList64'),row=run?.results?.[index];if(!list||!row)return;
    let current=list.querySelector(`[data-bench-result-id="${CSS.escape(String(row.id))}"]`);
    const shell=document.createElement('div');shell.innerHTML=rowHtml64(row,index);const next=shell.firstElementChild;
    if(current&&next)current.replaceWith(next);else if(next)list.appendChild(next);
    if(index===selectedIndex||!document.querySelector('#scenarioQuickEvidence64 .scn-inspection'))renderEvidenceWorkspace64(document.getElementById('scenarioQuickEvidence64'),run.results,'quick');
  }
  window.stopBenchBatch64=function(){if(state.benchBatch64?.running)state.benchBatch64.cancelled=true};

  window.runBenchBatch64=async function(){
    if(state.benchBatch64?.running)return toast('本次检测仍在进行中');
    if(state.benchBatch64?.outcomeUncertain)return toast('上次创建结果尚未确认，请先查询本次批次，不能盲目重试');
    const files=[...(state.benchFiles64||[])];if(!files.length)return toast('请先选择一张或多张图片');
    const mode=document.getElementById('benchMode64')?.value||'compare',conf=Math.max(0.001,Math.min(1,Number(document.getElementById('benchConf')?.value||.25)));
    const a=document.getElementById('benchModelA'),b=document.getElementById('benchModelB');
    if((mode==='compare'||mode==='a')&&!a?.value)return toast('请选择 A 模型');
    if((mode==='compare'||mode==='b')&&!b?.value)return toast('请选择 B 模型');
    const runId=`bench-${Date.now()}`,project=String(pid()),models={A:selectedModel64('A'),B:selectedModel64('B')},run={id:runId,mode,total:files.length,completed:0,success:0,failed:0,running:true,cancelled:false,results:files.map((file,index)=>({id:`${runId}-${index}`,batchId:runId,itemIndex:index,file,status:'pending',a:null,b:null,error:'',review:'',reviewNote:''}))};
    selectedIndex=0;state.benchBatch64=run;renderBenchBatch64();
    const button=document.getElementById('benchRun64');if(button){button.disabled=true;button.textContent='检测进行中…'}
    try{
      for(let index=0;index<run.results.length;index++){
        if(run.cancelled||state.benchBatch64!==run||String(pid())!==project)break;
        const row=run.results[index];row.status='running';patchBenchRow64(index);
        try{
          if(mode==='compare'||mode==='a'){row.pendingSide='A';row.a=await window.benchPredictOne('benchModelA',row.file,conf,{batch_id:run.id,item_index:index,item_total:run.total,side:'A',model:models.A,project_id:project,model_scope:'scenario',onProgress:task=>updateScenarioProgress64(run,task,project),original_filename:row.file.webkitRelativePath||row.file.name});}
          if(state.benchBatch64!==run||String(pid())!==project)break;
          if(run.cancelled){
            row.status=mode==='a'?'done':'partial';
            if(mode==='a'){run.success+=1;run.completed+=1;}
            for(const pending of run.results.slice(index+1))if(pending.status==='pending')pending.status='not_submitted';
            renderBenchBatch64();break;
          }
          if(mode==='compare'||mode==='b'){row.pendingSide='B';row.b=await window.benchPredictOne('benchModelB',row.file,conf,{batch_id:run.id,item_index:index,item_total:run.total,side:'B',model:models.B,project_id:project,model_scope:'scenario',onProgress:task=>updateScenarioProgress64(run,task,project),original_filename:row.file.webkitRelativePath||row.file.name});}
          row.status='done';run.success+=1;
        }catch(error){row.status=error.creationUncertain?'unknown':'failed';row.error=String(error?.message||error);if(error.creationUncertain){run.outcomeUncertain=true;run.cancelled=true;}else run.failed+=1;}
        if(row.status!=='unknown')run.completed+=1;if(String(pid())===project&&state.benchBatch64===run){patchBenchRow64(index);if(row.status==='done'&&!run.firstResultShown){run.firstResultShown=true;document.getElementById('scenarioQuickEvidence64')?.scrollIntoView({block:'start',behavior:'auto'});}}
      }
    }finally{
      run.running=false;if(String(pid())===project&&state.benchBatch64===run)summary64();
      if(button?.isConnected){button.disabled=!!run.outcomeUncertain;button.textContent=run.outcomeUncertain?'请先核验创建结果':'开始本次检测'}
      if(String(pid())===project)void window.loadDetectionBatches64?.({force:true});
    }
  };

  window.markBenchReview64=async function(index,value){
    const row=state.benchBatch64?.results?.[Number(index)];if(!row||!REVIEW_NAMES64[value])return;
    if(row.reviewSaving)return;row.reviewSaving=true;const project=String(pid());
    const status=document.getElementById('benchReviewStatus64');if(status)status.textContent='正在保存核验…';
    try{
      if(row.batchId){
        await api(`/api/v64/projects/${pid()}/detection-batches/${encodeURIComponent(row.batchId)}/items/${Number(row.itemIndex??index)}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({review:value,note:row.reviewNote||''})});
      }
      row.review=value;if(String(pid())===project&&state.benchBatch64?.results?.[Number(index)]===row)patchBenchRow64(Number(index));
      if(status)status.textContent=`已保存：${REVIEW_NAMES64[value]}`;
      void window.loadDetectionBatches64?.({force:true});
    }catch(error){if(status?.isConnected)status.textContent='保存失败';if(String(pid())===project)toast(error.message||error)}finally{row.reviewSaving=false;}
  };
  function canSubmitBenchFeedback64(value){
    return !!value?.task_id&&String(value?.m?.model_source||'').toLowerCase()==='algorithm_version'&&value?.m?.algorithm_id&&value?.m?.version_id;
  }
  window.openBenchFeedback64=async function(index,side){
    const batch=state.benchBatch64,row=batch?.results?.[Number(index)],value=String(side||'').toUpperCase()==='B'?row?.b:row?.a;
    if(!row||!canSubmitBenchFeedback64(value))return toast('只有正式算法版本的真实检测结果可以提交抽检反馈');
    const project=String(pid()),page=state.page,root=document.querySelector('.scenario-workbench'),selection=selectedIndex;
    const action=window.NavigationStability?.action?.(page),button=window.event?.currentTarget;
    const layers=[...document.querySelectorAll('.v424-modal-layer')],base=document.querySelector('#modal:not(.hidden)');
    const originModal=layers.at(-1)||base,belowModal=layers.length>1?layers.at(-2):originModal===base?null:base;
    const detail=button?.closest?.('.bench64-detail')||originModal?.querySelector?.('.bench64-detail');
    const topModal=()=>[...document.querySelectorAll('.v424-modal-layer')].at(-1)||document.querySelector('#modal:not(.hidden)');
    const owned=()=>String(pid())===project&&state.page===page&&state.benchBatch64===batch&&batch.results?.[Number(index)]===row
      &&selectedIndex===selection&&root?.isConnected&&document.querySelector('.scenario-workbench')===root&&(!action||action.isCurrent());
    const current=()=>owned()&&topModal()===originModal&&(!button||button.isConnected)&&(!detail||detail.isConnected&&originModal?.contains(detail));
    if(!current())return;
    if(button){button.disabled=true;button.textContent='正在准备证据…'}
    try{
      const prediction=await withRequestDeadline(signal=>api(`/api/v64/projects/${project}/deployment-tests/${encodeURIComponent(value.task_id)}/feedback-evidence`,{method:'POST',signal}),{label:'抽检反馈证据'});
      if(!current())return;
      if(detail){await closeModal();if(!owned()||topModal()!==belowModal)return;}
      state.lastOnlinePrediction63=prediction;
      window.openPredictionFeedback63?.();
    }catch(error){if(!current())return;toast(error.message||error);if(button?.isConnected){button.disabled=false;button.textContent='提交抽检反馈'}}
  };

  window.openBenchResult64=function(index){
    const row=state.benchBatch64?.results?.[Number(index)];if(!row||row.status!=='done')return;
    if(!row.previewUrl&&row.file instanceof File)row.previewUrl=URL.createObjectURL(row.file);
    const originalUrl=row.previewUrl||row.inputImageUrl||row.a?.r?.input_image_url||row.b?.r?.input_image_url||'';
    const result=(value,fallback)=>value?window.renderDetectionResult({...value.r,input_image_url:row.previewUrl||value.r?.input_image_url||originalUrl},resultName64(value,fallback)):'';
    const reviewButtons=Object.entries(REVIEW_NAMES64).map(([key,label])=>`<button class="btn mini ${row.review===key?'primary':'soft'}" onclick="markBenchReview64(${Number(index)},'${key}')">${label}</button>`).join('');
    const feedbackActions=[['A',row.a],['B',row.b]].filter(([,value])=>canSubmitBenchFeedback64(value)).map(([side,value])=>`<button class="btn primary" onclick="openBenchFeedback64(${Number(index)},'${side}')">${side==='A'?'检测模型':'对比模型'} · 提交抽检反馈</button>`).join('');
    modal('检测详情',`<div class="bench64-detail bench350-detail"><section class="bench64-original"><div class="panel-title">场景原图</div>${originalUrl?`<img src="${escAttr64(originalUrl)}" alt="检测原图" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span class="bench351-original-error" hidden>原图已不可访问，请检查历史检测文件是否仍保留。</span>`:'<div class="bench64-result-empty">原图地址不可用</div>'}<b>${esc(row.file?.webkitRelativePath||row.file?.name||row.originalFilename||'检测图片')}</b></section><div class="bench64-compare">${result(row.a,'检测模型')}${result(row.b,'对比模型')}</div><section class="bench64-review"><div><b>检测质量核验</b><span id="benchReviewStatus64">${row.review?'已标记：'+esc(REVIEW_NAMES64[row.review]):'尚未核验'}</span></div><div class="row wrap">${reviewButtons}</div><p>人工核验不会直接修改训练标注。</p></section>${feedbackActions?`<section class="bench64-feedback"><div><b>进入抽检复核</b><span>仅正式算法版本可提交。提交后先进入待复核，不会自动修改数据集或启动训练。</span></div><div class="row wrap">${feedbackActions}</div></section>`:''}</div>`,true);
  };

  function durableSide64(model){
    if(!model||model.status&&model.status!=='SUCCEEDED')return null;
    const identity=model.model||{};
    return {
      task_id:model.task_id||'',
      m:{label:identity.label||identity.model_name||identity.model_source||'模型',...identity},
      r:{
        detections:model.detections||[],image_url:model.result_image_url||'',input_image_url:model.input_image_url||'',
        preprocess_ms:model.preprocess_ms,inference_ms:model.inference_ms,postprocess_ms:model.postprocess_ms,total_elapsed_ms:model.total_elapsed_ms,
      }
    };
  }
  function batchFromDurable64(batch){
    const items=batch?.items||[],results=items.map(item=>{
      const a=durableSide64(item.models?.A),b=durableSide64(item.models?.B),statuses=[item.models?.A?.status,item.models?.B?.status].filter(Boolean);
      const failed=statuses.some(status=>status==='FAILED'),pending=statuses.some(status=>!['SUCCEEDED','FAILED','CANCELLED'].includes(String(status||'')));
      return {
        id:`${batch.batch_id}-${item.index}`,batchId:batch.batch_id,itemIndex:Number(item.index||0),
        file:{name:item.original_filename||`图片 ${Number(item.index||0)+1}`},originalFilename:item.original_filename||'',inputImageUrl:item.models?.A?.input_image_url||item.models?.B?.input_image_url||'',
        status:pending?'running':failed?'failed':'done',a,b,error:item.models?.A?.error||item.models?.B?.error||'',review:item.review?.review||'',reviewNote:item.review?.note||''
      };
    });
    return {id:batch.batch_id,mode:'restored',total:Number(batch.total||results.length),completed:Number(batch.completed_items||0),success:Math.max(0,Number(batch.completed_items||0)-Number(batch.failed_items||0)),failed:Number(batch.failed_items||0),running:false,cancelled:false,results};
  }
  window.renderDetectionBatchHistory64=function(){
    const root=document.getElementById('benchRecentBatches64');if(!root)return;
    const rows=state.detectionBatches64||[];
    root.innerHTML=rows.length?rows.map(batch=>`<button class="bench64-history-row" onclick="openDetectionBatch64('${escAttr64(batch.batch_id)}')"><span><b>${esc(batch.batch_id)}</b><em>${esc(batch.created_at||'')}</em></span><span>${Number(batch.created_items||0)} / ${Number(batch.total||0)} 张</span><span>${Number(batch.failed_items||0)} 失败</span><strong>查看结果 ›</strong></button>`).join(''):'<div class="bench64-empty"><b>暂无历史检测批次</b><span>完成一次批量检测后会出现在这里。</span></div>';
  };
  window.loadDetectionBatches64=async function({force=false}={}){
    const project=String(pid()),now=Date.now();
    if(state.detectionBatches64ProjectId!==project){state.detectionBatches64ProjectId=project;state.detectionBatches64=[];state.detectionBatches64LoadedAt=0;state.detectionBatches64Promise=null;}
    const age=now-Number(state.detectionBatches64LoadedAt||0);
    if(!force&&state.detectionBatches64LoadedAt&&age>=0&&age<30000){window.renderDetectionBatchHistory64();return state.detectionBatches64||[];}
    if(state.detectionBatches64Promise)return state.detectionBatches64Promise;
    const sequence=++historySequence,current=()=>String(pid())===project&&sequence===historySequence;
    const task=withRequestDeadline(signal=>api(`/api/v64/projects/${project}/detection-batches?limit=12`,{signal}),{label:'检测批次历史'}).then(result=>{
      if(!current())return [];state.detectionBatches64=result.items||[];state.detectionBatches64LoadedAt=Date.now();window.renderDetectionBatchHistory64();return state.detectionBatches64;
    }).catch(error=>{const root=document.getElementById('benchRecentBatches64');if(current()&&root&&error.name!=='AbortError')root.innerHTML=`<div class="alert err">${esc(error.message||error)}<button class="btn" onclick="loadDetectionBatches64({force:true})">重试</button></div>`;return [];}).finally(()=>{if(state.detectionBatches64Promise===task)state.detectionBatches64Promise=null;});
    state.detectionBatches64Promise=task;return task;
  };
  window.openDetectionBatch64=async function(batchId){
    if(state.benchBatch64?.running)return toast('本次检测进行中，完成或停止后再查看其他批次');
    const pending=state.benchBatch64;
    if(pending?.outcomeUncertain&&String(pending.id)!==String(batchId))return toast('创建结果待核验，请先查询原批次，不能用其他历史解除提交锁');
    const project=String(pid()),sequence=++batchOpenSequence;
    try{
      const result=await withRequestDeadline(signal=>api(`/api/v64/projects/${project}/detection-batches/${encodeURIComponent(batchId)}`,{signal}),{label:'检测批次结果'});
      if(String(pid())!==project||sequence!==batchOpenSequence||state.benchBatch64!==pending||!document.querySelector('.scenario-workbench'))return;
      if(!result.batch||String(result.batch.batch_id)!==String(batchId))throw new Error('返回批次身份不一致，请刷新历史');
      if(pending?.outcomeUncertain){
        const unresolved=(pending.results||[]).filter(row=>row.status==='unknown').some(row=>!result.batch.items?.some(item=>Number(item.index)===Number(row.itemIndex)&&item.models?.[row.pendingSide]?.task_id));
        if(unresolved)return toast('原批次尚未确认本次请求的任务身份，请稍后继续查询，禁止重复创建');
      }
      state.benchBatch64=batchFromDurable64(result.batch);window.setScenarioMode64('quick');window.renderBenchBatch64();
      const button=document.getElementById('benchRun64');if(button){button.disabled=false;button.textContent='开始本次检测';}
    }catch(error){if(String(pid())===project&&sequence===batchOpenSequence&&state.benchBatch64===pending&&error.name!=='AbortError')toast(error.message||error);}
  };

  function benchNotices64(models,ready){
    return `${models.length?'':'<div class="alert">暂无符合资格的成功训练版本。母模型、未验证PT和失败Checkpoint不可进入场景实测。</div>'}${ready?'':'<div class="alert warn">暂无可用推理 Runtime；仍可查看可信独立评测，准备资源后才能检测图片。</div>'}`;
  }
  function patchBenchModelBrowser64(side){
    const select=document.getElementById(`benchModel${side}`),algorithm=document.getElementById(`benchAlgorithm${side}`);if(!select||!algorithm)return false;
    const current=select.dataset.modelIdentity||'',oldAlgorithm=algorithm.value;
    const signature=JSON.stringify(detectionModels64().map(m=>[m.algorithm_id,m.version_id,m.model_sha256,m.version_name,m.finished_at,m.created_at]));
    if(select.dataset.modelsSignature===signature)return false;
    select.dataset.modelsSignature=signature;algorithm.innerHTML=algorithmOptions64(oldAlgorithm);
    if([...algorithm.options].some(o=>o.value===oldAlgorithm))algorithm.value=oldAlgorithm;
    const match=detectionModels64().find(m=>`${m.algorithm_id}:${m.version_id}`===current);
    const preferred=match?(state.scenarioTestModels||[]).indexOf(match):defaultModelIndex64(side);
    select.innerHTML=modelOptions64('',preferred,algorithm.value);select.dataset.modelIdentity=selectedModel64(side)?`${selectedModel64(side).algorithm_id}:${selectedModel64(side).version_id}`:'';
    if(side==='A'&&select.dataset.modelIdentity!==current){reportVersion=null;reportModel=null;void loadScenarioReport64();}
    return true;
  }
  window.toggleBenchComparison64=function(show){
    const root=document.querySelector('[data-quality-detection-shell="1"]');if(!root)return;
    const enabled=!!show;root.classList.toggle('bench350-comparison',enabled);
    const button=document.getElementById('benchAddCompare64');if(button)button.textContent=enabled?'移除对比模型':'＋ 添加对比模型';
    const select=document.getElementById('benchMode64');if(select)select.value=enabled?'compare':'a';void loadScenarioComparison64();
  };
  window.syncBenchComparisonMode64=function(value){
    const root=document.querySelector('[data-quality-detection-shell="1"]');if(root)root.classList.toggle('bench350-comparison',value==='compare'||value==='b');
  };
  function qualityDetectionShell64(models,ready){
    return `<div class="bench64-shell bench350-shell scenario-workbench" data-quality-detection-shell="1"><header class="scn-head"><div><h2>场景算法实测</h2><p>从可信独立测试到具体图片，核查模型表现与错误证据</p></div><button class="btn" onclick="refreshDetectionBenchDataV3()">刷新模型</button></header><div id="benchNotices64">${benchNotices64(models,ready)}</div><div class="scn-selection"><div class="bench64-model-grid bench350-model-grid">${modelBrowser64('A','评估算法')}${modelBrowser64('B','对比算法')}</div><button type="button" id="benchAddCompare64" class="btn" onclick="toggleBenchComparison64(!document.querySelector('.bench350-shell')?.classList.contains('bench350-comparison'))">＋ 添加对比模型</button></div><nav class="scn-tabs" role="tablist" aria-label="实测模式"><button class="btn" role="tab" data-scenario-mode="accuracy" aria-selected="true" onclick="setScenarioMode64('accuracy')">准确性评测</button><button class="btn" role="tab" data-scenario-mode="quick" aria-selected="false" onclick="setScenarioMode64('quick')">快速图片检测</button></nav><section id="scenarioAccuracy64"></section><section id="scenarioQuick64" hidden><div class="scn-inputs"><div><label>置信度<input id="benchConf" class="input" type="number" min="0.001" max="1" step="0.01" value="0.25"></label></div><div class="scn-file-actions" role="group" aria-label="场景来源"><button class="btn" onclick="document.getElementById('benchFiles64').click()">选择场景图片</button><button class="btn" onclick="document.getElementById('benchFolder64').click()">选择文件夹</button><button class="btn soft" onclick="clearBenchFiles64()">清空本次</button><input id="benchFiles64" type="file" accept="image/*" multiple hidden onchange="addBenchFiles64(this)"><input id="benchFolder64" type="file" accept="image/*" multiple webkitdirectory directory hidden onchange="addBenchFiles64(this)"></div><button id="benchRun64" class="btn primary" onclick="runBenchBatch64()">开始本次检测</button><select id="benchMode64" class="select" onchange="syncBenchComparisonMode64(this.value)"><option value="a">只测 A 模型</option><option value="compare">同图 A / B 对比</option><option value="b">只测 B 模型</option></select></div><div class="scn-file-heading"><b id="benchFileCount64">尚未选择图片</b><span>无正式 GT 的图片仅显示预测与人工复核，不计算准确率或 TP / FP / FN。</span></div><div id="benchFileList64" class="bench64-file-list"></div><div id="benchPreview64" class="bench64-preview" hidden></div><div id="benchResult" class="bench64-live"></div><section class="bench64-results"><h3>本次检测结果</h3><div id="benchBatchSummary64"></div><div id="benchBatchList64" class="bench64-result-list" hidden></div><div id="scenarioQuickEvidence64"></div></section></section><details class="bench64-history scn-history"><summary>最近检测批次</summary><div class="row end"><button class="btn small" onclick="loadDetectionBatches64({force:true})">刷新历史</button></div><div id="benchRecentBatches64"></div></details></div>`;
  }
  window.renderQualityDetectionBench64=function renderQualityDetectionBench64(){
    const view=document.getElementById('view');if(!view)return;
    const project=String(pid());
    if(mountedProject&&mountedProject!==project){deactivate64();state.benchBatch64=null;state.benchFiles64=[];if(state.scenarioModelsProjectId!==project)state.scenarioTestModels=[];displayMode='accuracy';}
    mountedProject=project;
    const models=detectionModels64(),ready=(state.inferenceEnvs||[]).some(env=>env?.status==='ready');
    let shell=view.querySelector('[data-quality-detection-shell="1"]'),mounted=false;
    if(!shell){
      view.innerHTML=qualityDetectionShell64(models,ready);
      shell=view.querySelector('[data-quality-detection-shell="1"]');
      mounted=true;
    }else{
      const notices=document.getElementById('benchNotices64'),nextNotices=benchNotices64(models,ready);
      if(notices&&notices.innerHTML!==nextNotices)notices.innerHTML=nextNotices;
      patchBenchModelBrowser64('A');patchBenchModelBrowser64('B');
    }
    if(mounted){
      window.renderBenchFileQueue64();window.renderBenchBatch64();window.renderDetectionBatchHistory64();
      patchBenchModelBrowser64('A');patchBenchModelBrowser64('B');window.setScenarioMode64('accuracy');
    }else{
      summary64();window.renderDetectionBatchHistory64();
    }
    void window.loadDetectionBatches64();window.renderOnlineFeedbackPanel63?.(view);
  };

  function deactivate64(){comparisonController?.abort();comparisonSequence++;comparison={};reportViews()?.disposeReportViews?.(document.querySelector('.scenario-workbench'));reportController?.abort();reportSequence++;reportLoading=false;reportError='';reportVersion=null;reportModel=null;batchOpenSequence++;revokeEvidenceUrls64();}
  function mountEvaluationEvidence(root,{model,version,rows,comparison:other}={}){
    deactivate64();displayMode='accuracy';selectedIndex=0;zoom=1;classFilter='';issueFilter='';matrixCell=null;confidence=0;showGT=true;showPred=true;
    reportModel=model;reportVersion={...version,evaluation:{...version.evaluation,error_samples:rows||[]}};
    comparison=other||{};root.classList.add('scenario-workbench');root.id='scenarioEvidence64';
    renderEvidenceWorkspace64(root,rows||[],'evaluation');renderScenarioAnalysis64();
  }
  return {render:window.renderQualityDetectionBench64,deactivate:deactivate64,destroy:deactivate64,mountEvaluationEvidence,currentEvaluationSample:()=>reportVersion?.evaluation?.error_samples?.[selectedIndex]||null};
}
