export function reportPresentation(report = {}) {
  if (report.report_type === 'algorithm') {
    return {title: '算法综合训练报告', scope: 'algorithm'};
  }
  return {title: '单版本训练报告', scope: 'version'};
}

const escapeText = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const finite = value => ['number','string'].includes(typeof value) && String(value).trim() !== '' && Number.isFinite(Number(value)) ? Number(value) : null;

export function formatPercentagePointDelta(value) {
  const numeric = finite(value);
  if (numeric === null) return '未记录';
  return `${numeric > 0 ? '+' : ''}${(numeric * 100).toFixed(1)} pp`;
}

export function metricChart(rows = [], key, title, {xKey='epoch',percent=false} = {}) {
  const points=rows.slice(-1000).map(row=>({x:finite(row[xKey]),y:finite(row[key])}));
  const valid=points.filter(point=>point.x!==null&&point.y!==null);
  if(!valid.length)return `<section class="quality-chart"><header>${escapeText(title)}</header><div class="quality-empty">暂无记录</div></section>`;
  const minX=Math.min(...valid.map(p=>p.x)),maxX=Math.max(...valid.map(p=>p.x));
  const minY=percent?0:Math.min(...valid.map(p=>p.y)),maxY=percent?1:Math.max(...valid.map(p=>p.y));
  const x=p=>48+(p.x-minX)/Math.max(.000001,maxX-minX)*564,y=p=>158-(p.y-minY)/Math.max(.000001,maxY-minY)*126;
  let drawing=false;
  const path=points.map(p=>{if(p.x===null||p.y===null){drawing=false;return '';}const command=drawing?'L':'M';drawing=true;return `${command}${x(p).toFixed(2)},${y(p).toFixed(2)}`;}).join(' ');
  const format=value=>percent?(value*100).toFixed(1)+'%':value.toFixed(4);
  const best=percent?valid.reduce((a,b)=>b.y>a.y?b:a):null,last=valid.at(-1);
  return `<section class="quality-chart"><header><b>${escapeText(title)}</b><span>${valid.length} 个真实记录</span></header><svg viewBox="0 0 640 195" role="img" aria-label="${escapeText(title)}"><path d="M48 32H612 M48 95H612 M48 158H612" class="quality-chart-grid"/><text x="4" y="36">${format(maxY)}</text><text x="4" y="160">${format(minY)}</text><path d="${path}" class="quality-chart-line"/>${valid.map(p=>`<circle tabindex="0" cx="${x(p)}" cy="${y(p)}" r="3"><title>${escapeText(xKey)} ${p.x} · ${escapeText(title)} ${format(p.y)}</title></circle>`).join('')}${best?`<circle class="quality-chart-best" cx="${x(best)}" cy="${y(best)}" r="5"><title>最佳已记录值 · ${escapeText(xKey)} ${best.x} · ${format(best.y)}</title></circle>`:''}<text x="48" y="185">${escapeText(xKey)} ${minX}</text><text text-anchor="end" x="612" y="185">${last.x} · 最后记录</text></svg></section>`;
}

export function trainingCharts(history = [], samples = []) {
  const groups=trainingChartGroups(history,samples);
  if(!groups.length)return '<div class="quality-empty">暂无训练曲线记录；不根据最终指标补造 Epoch 曲线。</div>';
  return `<div class="report-chart-groups">${groups.map(group=>`<section class="report-chart-card"><header><b>${escapeText(group.title)}</b><small>悬停查看 · 图例筛选 · 滚轮/拖动缩放</small></header><div class="report-interactive-chart" data-report-chart="${group.key}" role="img" aria-label="${escapeText(group.title)}交互图表"></div><div data-chart-fallback hidden>${group.fields.map(([key,title,percent])=>metricChart(group.rows,key,title,{xKey:group.xKey,percent})).join('')}</div></section>`).join('')}</div>`;
}

const metricCredibilityReasons = Object.freeze({
  independent_test_unavailable: '独立 Test 未完成，只有验证集结果',
  independent_test_metric_or_samples_missing: '独立 Test 缺少有效指标或实际样本数',
  validation_test_map50_gap_at_least_10pp: '验证集与独立 Test 的 mAP50 差距达到 10 个百分点',
  test_class_coverage_unverified: '独立 Test 的模型类别目录未完整确认',
  independent_test_classes_without_gt: '独立 Test 中部分模型类别没有正样本',
  independent_test_no_scored_positive_classes: '独立 Test 没有真实参与评分的正样本类别',
  frozen_split_coverage_unavailable: '缺少本轮冻结划分的类别覆盖证据',
  validation_classes_without_gt: '验证集缺少已训练类别的正样本',
  split_test_classes_without_gt: '冻结 Test 缺少已训练类别的正样本',
  capture_source_evidence_missing: '缺少摄像头、视频或采集来源的完整记录',
  capture_source_partly_unknown: '部分素材的拍摄来源未知',
  test_independent_component_counts_missing: '无法确认 Test 的独立来源组数量',
  test_class_fewer_than_three_independent_groups: '部分测试类别少于 3 个独立来源组',
  test_positive_image_support_missing: '缺少 Test 各类别正样本图片数量',
  test_class_fewer_than_five_positive_images: '部分测试类别少于 5 张正样本图片',
  independent_test_inference_protocol_incomplete: '独立测试图片尺寸、置信度或推理协议不完整',
  independent_test_input_binding_unverified: '测试图片与标注尚无不可变输入绑定证明',
  source_or_projected_gt_needs_review: '原始或训练投影标注仍有待人工复核项',
  model_class_catalog_differs_from_frozen_training_labels: '模型类别目录与本次冻结标签不一致',
  test_scored_images_differ_from_frozen_selection: '实际 Test 图片数与冻结选择数量不符'
});

/** Render only the server's persisted TQ-04 evidence. No client-side scoring. */
export function metricCredibilityHtml(value) {
  if (!value || typeof value !== 'object' || value.schema_version !== 1) {
    return '<section class="report429-card" data-metric-credibility="unavailable"><header><b>模型高分可信度</b><span>历史证据缺失</span></header><p>该版本没有冻结的可信度诊断，不能根据当前素材或高 mAP 推断真实泛化效果。</p></section>';
  }
  // The backend owns the result. A malformed stored value is missing
  // evidence, never a percentage invented from coercion (e.g. true -> 100%).
  const unitScore = raw => {
    if (typeof raw !== 'number' || !Number.isFinite(raw) || raw < 0 || raw > 1) return null;
    return raw;
  };
  const percent = raw => {
    const score = unitScore(raw);
    return score === null ? '未记录' : `${(score * 100).toFixed(1)}%`;
  };
  const gap = raw => {
    if (typeof raw !== 'number' || !Number.isFinite(raw) || raw < -1 || raw > 1) return '未记录';
    const value = raw * 100;
    return `${value > 0 ? '+' : ''}${value.toFixed(1)} pp`;
  };
  const imageCount = Number.isSafeInteger(value.test_image_count) && value.test_image_count >= 0
    ? String(value.test_image_count) : '未记录';
  const status = {
    review_required: '需人工复核',
    held_out_evidence_present: '已获得独立 Test 证据',
    val_metric_unavailable: '验证指标缺失',
    not_high_val_trigger: '未触发高分复核'
  }[value.status] || '证据状态未知';
  const bindingLevel = ({
    bundle_verified: '已绑定校验的数据包',
    snapshot_truth: '仅冻结 Test 来源',
    unavailable: '缺少绑定证明'
  })[value.independent_test_binding_level] || '未记录';
  const reasons = Array.isArray(value.reason_codes) ? value.reason_codes : [];
  const issues = reasons.slice(0, 25).map(code => `<li>${escapeText(metricCredibilityReasons[String(code)] || String(code))}</li>`).join('');
  const val = percent(value.validation_map50);
  const tst = percent(value.independent_test_map50);
  return `<section class="report429-card" data-metric-credibility="${escapeText(value.status || 'unknown')}">
    <header><b>模型高分可信度</b><span>${escapeText(status)}</span></header>
    <div class="quality-metrics"><div><span>验证集 Val mAP50</span><b>${val}</b></div><div><span>独立 Test mAP50</span><b>${tst}</b></div><div><span>Val − Test</span><b>${gap(value.val_minus_test_map50)}</b></div><div><span>独立 Test 实际图片</span><b>${imageCount}</b></div><div><span>独立 Test 输入绑定</span><b>${escapeText(bindingLevel)}</b></div></div>
    ${issues ? `<p>待核实的证据（并非数据泄漏已被证实）：</p><ul>${issues}</ul>` : '<p>当前未触发已定义的高分复核项，但仍不代表生产场景已经验收。</p>'}
    <p class="item-sub">mAP 是目标检测指标，不是事件告警准确率；本诊断不判断造假，也不替代现场业务验收。</p>
  </section>`;
}


const CHATGPT_ANALYSIS_INSTRUCTIONS = `你是一名熟悉 Ultralytics YOLO、目标检测训练、数据集治理、模型评测和边缘部署的算法工程师。

请依据以下真实训练数据和用户补充的业务信息，对本次模型训练进行技术分析。
请特别注意：
1. 区分训练成功、模型精度合格和实际业务可用。
2. 区分 Train、Val 和独立 Test。
3. 不要把 mAP50 直接理解为业务准确率。
4. 判断数据是否充分支持精度和泛化结论。
5. 分析收敛情况与可能的过拟合风险。
6. 分析 FP、FN、类别混淆和主要质量短板。
7. 判断训练精度、图片尺寸、Epoch、Batch、Workers、优化器和学习率是否合理。
8. 结合实际业务需求判断精度是否可能够用；若验收要求不足，说明无法确认并列出所需信息。
9. 判断是否需要重新训练、迭代微调，或只需调整推理阈值与部署配置。
10. 给出下一轮最值得进行的少量改进实验，包括具体建议、预期收益和验收方式。
11. 对每个结论标明属于已证实、合理怀疑还是证据不足。
12. 不得补造缺失的指标、异常图片、测试结果或设备性能。
13. 优先选择低风险、高价值的改进方案，不要无依据要求增加 Epoch、提高 imgsz 或扩大模型。
14. 如果需要进一步判断，请明确说明用户还应提供哪些实际场景图片、业务指标、模型日志或其他证据。

请输出：
A. 本次训练整体评价。
B. 指标可信度与是否满足业务目标。
C. 训练参数和资源效率分析。
D. 主要问题及其证据。
E. 是否需要重新训练及具体理由。
F. 下一版本优化实验计划，按优先级排序。
G. 尚缺哪些证据。

下面是本次训练报告事实：`;

function analysisText(value, limit=4000) {
  return String(value ?? '').slice(0,limit)
    .replace(/(?:https?|s3|oss):\/\/[^\s<>"']+/gi,'[链接已隐藏]')
    .replace(/(?:Bearer\s+)[\w.\-]+/gi,'[凭证已隐藏]')
    .replace(/(["']?)(?:access[_-]?token|refresh[_-]?token|id[_-]?token|api[_-]?key|access[_-]?key(?:[_-]?(?:id|secret))?|secret[_-]?access[_-]?key|token|secret|password|signature|authorization)\1\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;}]+)/gi,'[凭证已隐藏]')
    .replace(/\b(?:sk|AKIA)-?[A-Za-z0-9_-]{16,}\b/g,'[凭证已隐藏]')
    .replace(/\\\\[^\s<>"']+/g,'[路径已隐藏]')
    .replace(/[A-Za-z]:[\\/][^\s,;<>"']+/g,'[路径已隐藏]')
    .replace(/(?:^|\s)(?:\/[\w.\-\u4e00-\u9fff]+){2,}(?:\.[\w]+)?/g,' [路径已隐藏]');
}
function analysisValue(value) {
  if(value===undefined||value===null||value==='')return '未记录';
  if(typeof value==='number')return Number.isFinite(value)?String(value):'未记录';
  if(typeof value==='boolean')return value?'是':'否';
  if(Array.isArray(value))return value.length?value.slice(0,1000).map(analysisValue).join('；'):'未记录';
  if(typeof value==='object')return Object.keys(value).filter(key=>!/(?:token|secret|password|authorization|credential|api.?key|signed.?url|(?:^|_)path$)/i.test(key)).sort().map(key=>`${analysisText(key)}=${analysisValue(value[key])}`).join('，')||'未记录';
  return analysisText(value);
}
function analysisMetric(metrics={},key,aliases=[]) {
  for(const name of [key,...aliases])if(finite(metrics?.[name])!==null)return finite(metrics?.[name]);
  return null;
}
export function trainingHistoryRows(history=[]) {
  return history.slice(-1000).filter(row=>finite(row?.epoch)!==null).map(row=>({epoch:finite(row.epoch),
    precision:analysisMetric(row,'precision')??analysisMetric(row.metrics,'metrics/precision(B)'),
    recall:analysisMetric(row,'recall')??analysisMetric(row.metrics,'metrics/recall(B)'),
    map50:analysisMetric(row,'map50')??analysisMetric(row.metrics,'metrics/mAP50(B)'),
    map5095:analysisMetric(row,'map5095')??analysisMetric(row.metrics,'metrics/mAP50-95(B)'),
    box_loss:analysisMetric(row,'box_loss')??analysisMetric(row.losses,'box_loss',['train/box_loss']),
    cls_loss:analysisMetric(row,'cls_loss')??analysisMetric(row.losses,'cls_loss',['train/cls_loss']),
    dfl_loss:analysisMetric(row,'dfl_loss')??analysisMetric(row.losses,'dfl_loss',['train/dfl_loss']),
    val_box_loss:analysisMetric(row,'val_box_loss')??analysisMetric(row.metrics,'val/box_loss'),
    val_cls_loss:analysisMetric(row,'val_cls_loss')??analysisMetric(row.metrics,'val/cls_loss'),
    val_dfl_loss:analysisMetric(row,'val_dfl_loss')??analysisMetric(row.metrics,'val/dfl_loss'),
    learning_rate:analysisMetric(row,'learning_rate')??analysisMetric(row.learning_rates,'lr/pg0'),
    duration_seconds:analysisMetric(row,'duration_seconds'),images_per_second:analysisMetric(row,'images_per_second'),
  })).sort((a,b)=>a.epoch-b.epoch);
}
function analysisMetricLines(metrics={}) {
  const p=analysisMetric(metrics,'precision',['metrics/precision(B)']),r=analysisMetric(metrics,'recall',['metrics/recall(B)']);
  const pairValid=p!==null&&r!==null&&p>=0&&p<=1&&r>=0&&r<=1;
  return `Precision=${analysisValue(p)}，Recall=${analysisValue(r)}，mAP50=${analysisValue(analysisMetric(metrics,'map50',['metrics/mAP50(B)','mAP50']))}，mAP50-95=${analysisValue(analysisMetric(metrics,'map5095',['metrics/mAP50-95(B)']))}，F1=${pairValid?analysisValue(p+r?2*p*r/(p+r):0):'未记录（缺少同口径P/R）'}`;
}

function currentReportFacts({job={},report={}}={}) {
  const id=report.identity||{job_id:report.job_id,version_id:report.version_id};
  if((id.job_id&&job.id&&String(id.job_id)!==String(job.id))||(id.version_id&&job.auto_version_id&&String(id.version_id)!==String(job.auto_version_id)))throw new Error('报告与当前训练任务或版本身份不一致');
  const requested={...(report.configuration||{}),...(job.requested_train_params||{}),...(report.requested_train_params||{})};
  if(requested.epochs==null&&job.requested_epochs!=null)requested.epochs=job.requested_epochs;
  return {...report,requested_train_params:requested,
    actual_train_params:{...(job.actual_train_params||{}),...(report.actual_train_params||{})},
    completed_epochs:report.completed_epochs??job.completed_epochs??job.current_epoch,
    completion_reason:report.completion_reason??job.completion_reason,
    status:report.status??job.task_status??job.status,
    identity:report.identity||{job_id:report.job_id||job.id,version_id:report.version_id||job.auto_version_id},
  };
}

/** Pure, bounded formatter of the current report; it performs no fetch or AI call. */
export function chatGPTAnalysisMaterial({job={},report={}}={},supplements={}) {
  report=currentReportFacts({job,report});
  const id=report.identity||{job_id:report.job_id,version_id:report.version_id};
  const requested=report.requested_train_params||{},actual=report.actual_train_params||{};
  const runtime=report.runtime_metrics||{},lineage=report.lineage||{},base=lineage.base||{},evaluation=report.evaluation||{};
  const lines=[CHATGPT_ANALYSIS_INSTRUCTIONS,'生成方式：固定模板确定性组装；指标为0–1原始值，未知不等于0。'];
  const add=(label,value)=>lines.push(`${label}：${analysisValue(value)}`);
  const section=title=>lines.push('',title);
  section('A. 模型身份与训练任务（来源：当前报告identity、冻结版本与任务）');
  add('算法名称',id.algorithm_name);add('算法版本ID',id.version_id);add('训练任务ID',id.job_id);add('框架',report.framework);
  add('真实架构',report.model_architecture);add('母模型',(report.base_model_path||base.model||'').split(/[\\/]/).pop());
  add('首次/迭代',report.base_version_id||base.version_id?'版本迭代':report.base_selection_reason||'未记录，不能据空母版本推断首次训练');
  add('上一版本',report.base_version_id||base.version_id);add('母模型身份SHA256',base.sha256);
  add('类别数量',Array.isArray(report.class_mapping)&&report.class_mapping.length?report.class_mapping.length:null);
  add('冻结类别ID与名称',report.class_mapping?.map(row=>({class_id:row.class_id,code:row.code,name:row.name||row.display_name||row.code})));
  add('真实状态',report.status);add('开始时间',report.started_at);add('完成时间',report.finished_at);
  section('B. 数据集与划分（来源：冻结Snapshot、数据版本与原审计）');
  add('数据集版本',report.dataset_revision_id);add('训练快照',report.snapshot_id);
  add('Train/Val/Test图片数量',report.data_summary?.counts||report.dataset_counts);
  add('每类正样本图片与GT框',report.frozen_data_quality?.classes);
  add('负样本数量',report.frozen_data_quality?.negative_count??report.frozen_data_quality?.empty_image_count);
  add('采集来源/摄像头/视频分组',report.capture_source_summary);
  add('冻结及重复/近重复/GT冲突/跨分区泄漏审计',report.frozen_audit);
  add('指标可信度',report.metric_credibility);
  add('Test独立基准身份',evaluation.benchmark_scope);
  lines.push('未记录来源或泄漏审计不代表不存在泄漏；独立Test与业务验收均须真实证据。');
  section('C. 请求、系统决议与实际执行参数（来源：冻结请求、资源决议与Trainer回执）');
  for(const [key,label] of [['epochs','Epoch'],['imgsz','imgsz'],['batch','Batch'],['workers','Workers'],['precision','训练精度'],['optimizer','Optimizer'],['lr0','lr0'],['patience','Patience'],['cos_lr','Cos LR'],['warmup_epochs','Warmup'],['mosaic','Mosaic'],['mixup','MixUp'],['close_mosaic','Close Mosaic']])add('请求'+label,requested[key]);
  for(const [key,label] of [['batch','Batch'],['workers','Workers']])add('实际'+label,runtime['runtime_'+key]??actual['runtime_'+key]??actual[key]);
  add('实际训练精度（冻结运行记录）',actual.effective_precision??actual.precision);add('实际imgsz',actual.imgsz);
  add('实际完成Epoch',report.completed_epochs);add('真实最佳Checkpoint Epoch',report.best_epoch);
  add('实际Optimizer',runtime.runtime_optimizer??actual.runtime_optimizer);add('实际初始LR',runtime.runtime_initial_learning_rates??actual.runtime_initial_learning_rates);
  add('实际AMP',runtime.amp_runtime_enabled??actual.amp_runtime_enabled);add('实际GPU/Worker',report.execution);
  add('系统资源决议',Object.fromEntries(['resolved_batch','resolved_workers','resolved_precision','adjustments','reasons'].map(key=>[key,runtime[key]])));
  add('Early Stopping与完成原因',{enabled:requested.early_stopping_enabled,reason:report.completion_reason});
  lines.push('optimizer=auto的请求lr0不是实际初始学习率；Workers=0本身不能确诊I/O瓶颈。');
  section('D. 真实训练曲线摘要（来源：当前任务有记录Epoch，最多1000条）');
  const history=trainingHistoryRows(report.history||[]),scored=history.filter(row=>row.map50!==null),best=scored.reduce((a,b)=>!a||b.map50>a.map50?b:a,null);
  add('曲线记录数量',history.length);add('最佳已记录Epoch（按Val mAP50，非Checkpoint身份）',best?.epoch);add('对应Val mAP50',best?.map50);add('最后有记录Epoch',history.at(-1)?.epoch);
  const indices=[...new Set([0,Math.floor(history.length/4),Math.floor(history.length/2),Math.floor(history.length*3/4),history.length-1])].filter(i=>i>=0&&i<history.length);
  for(const i of indices)add('关键采样Epoch '+history[i].epoch,history[i]);
  const observed=history.filter(row=>row.map50!==null).slice(-10);
  add('最后阶段可观测变化',observed.length>=6?{records:observed.length,first_epoch:observed[0].epoch,last_epoch:observed.at(-1).epoch,map50_change:observed.at(-1).map50-observed[0].map50}:'数据不足，无法判断');
  add('缺失曲线',Object.keys(history[0]||{precision:null,recall:null,map50:null,map5095:null,box_loss:null,val_box_loss:null,learning_rate:null}).filter(key=>key!=='epoch'&&!history.some(row=>row[key]!==null)));
  lines.push('以上仅为记录和数值趋势，不确诊过拟合、数据不足或模型达到业务要求。');
  section('E. 模型评测结果（保持Train、Validation、独立Test及协议隔离）');
  add('Train过程指标',report.train_metrics?analysisMetricLines(report.train_metrics):null);
  add('训练阶段评测协议（非独立Test）',report.data_summary?.quality_gate);
  add('Validation指标',analysisMetricLines(report.metrics));add('Validation逐类别',report.per_class);
  add('独立Test状态',evaluation.status);add('独立Test指标',evaluation.status==='succeeded'?analysisMetricLines(evaluation.metrics):null);
  add('独立Test逐类别',evaluation.status==='succeeded'?evaluation.per_class:null);
  add('Test支持量',{images:evaluation.image_count,gt_boxes:evaluation.ground_truth_box_count,predictions:evaluation.prediction_box_count});
  add('Test Confidence/IoU/尺寸协议',evaluation.protocol);add('Test基准完整性',evaluation.benchmark_scope);
  add('混淆信息',evaluation.confusion_matrix);lines.push('不计算不同数据集或协议之间的指标差值。未记录独立Test不能证明泛化或业务合格。');
  section('F. 代表性异常样本（来源：当前报告已核验的冻结FP/FN引用）');
  const errors=report.representative_errors||{};add('样本证据状态',errors.status||errors.reason);
  for(const [i,row] of (errors.items||[]).slice(0,12).entries())add('匿名样本 '+(i+1),{type:[row.fp_count?'FP':'',row.fn_count?'FN':''].filter(Boolean).join('/'),classes:[...(row.fp_labels||[]),...(row.fn_labels||[])],fp:row.fp_count,fn:row.fn_count,gt_count:row.boxes_truncated?null:row.gt_boxes?.length,prediction_count:row.boxes_truncated?null:row.pred_boxes?.length,confidence:row.pred_boxes?.map(b=>b.confidence),preview:'需原冻结图片接口身份校验',iou:row.match_iou});
  if(!errors.items?.length)lines.push('未记录可核验的真实错误样本，不描述不存在的图片或原因。');
  lines.push('如果希望分析错误图片，请用户手动附上报告中有代表性的异常图片，并确认有权外传；本材料不含图片字节。');
  section('G. 训练资源效率（来源：实际遥测，未采样不推断）');
  add('总训练时长（秒）',report.elapsed_seconds??runtime.total_duration_seconds);
  const durations=history.map(r=>r.duration_seconds).filter(v=>v!==null);
  add('平均Epoch耗时（秒）',durations.length?durations.reduce((a,b)=>a+b,0)/durations.length:null);add('最快Epoch耗时（秒）',durations.length?Math.min(...durations):null);
  add('采样范围与覆盖',report.resource_coverage);add('吞吐/GPU/显存/CPU/内存/IO Wait',report.resource_summary);
  add('真实资源诊断',runtime.diagnostic);
  section('H. 转换与部署情况（来源：当前版本ModelArtifact及转换任务快照）');
  for(const row of report.conversions||[]){const meta=row.metadata||{};add('转换成果',{vendor:meta.local_vendor_id,target:row.target,chip:row.chip_code,source_precision:meta.source_training_precision,compiler_precision:meta.precision,width:meta.image_width??meta.conversion_params?.input_width,height:meta.image_height??meta.conversion_params?.input_height,artifact_id:row.artifact_id,sha256:row.sha256,job_id:row.conversion_job_id,validation:meta.validation_status,device_load:meta.hardware_verified,real_image_inference:meta.real_image_inference_verified,board_performance:meta.board_performance});}
  if(!report.conversions?.length)lines.push('未转换或未记录可信的当前版本转换成果。');
  lines.push('基础或合成图片推理PASS不证明真实业务检测准确率；输入/输出FP32也不证明内部编译精度。');
  section('用户补充实际场景（可选）');lines.push('用户提供的现场描述，尚未由训练系统独立验证。');
  for(const [key,label] of [['scenario','实际业务场景与摄像头环境'],['target','期望指标与可接受误报漏报'],['observed','现场已观察问题'],['deployment','计划硬件、分析频率与性能要求']])add(label,supplements[key]?.trim()||null);
  lines.push('若现场证据不足，请明确询问还需哪些场景图片、业务指标、日志和设备证据，不要臆造现场结论。');
  if(report.evidence_fixture)lines.push('验收标识：以上为真实结构的隔离测试数据，不是生产指标或真实业务验收结果。');
  return analysisText(lines.join('\n'),100000);
}


function reportTooltipPosition(point,params,dom,rect,size) {
  const [x,y]=point,[width,height]=size.contentSize,[viewWidth,viewHeight]=size.viewSize;
  return [Math.max(0,Math.min(x+16,viewWidth-width-8)),Math.max(0,Math.min(y+16,viewHeight-height-8))];
}

export function trainingChartGroups(history=[],samples=[]) {
  const rows=trainingHistoryRows(history),resourceRows=samples.slice(-720).filter(row=>row&&typeof row.sampled_at==='string').map((row,index)=>({...row,sample:index+1}));
  const definitions=[
    ['accuracy','Validation 指标',rows,'epoch',[['precision','Precision',true],['recall','Recall',true],['map50','mAP50',true],['map5095','mAP50-95',true]]],
    ['train-loss','训练损失',rows,'epoch',[['box_loss','Train Box Loss'],['cls_loss','Train Class Loss'],['dfl_loss','Train DFL Loss']]],
    ['val-loss','验证损失',rows,'epoch',[['val_box_loss','Val Box Loss'],['val_cls_loss','Val Class Loss'],['val_dfl_loss','Val DFL Loss']]],
    ['learning-rate','实际学习率',rows,'epoch',[['learning_rate','LR / pg0']]],
    ['epoch-time','Epoch 耗时 / 秒',rows,'epoch',[['duration_seconds','Epoch 耗时（秒）']]],
    ['throughput','训练吞吐 / 图片每秒',rows,'epoch',[['images_per_second','图片/秒']]],
    ['utilization','资源利用率 / %',resourceRows,'sample',[['gpu_utilization','GPU %'],['gpu_memory_percent','GPU 显存 %'],['cpu_percent','CPU %'],['memory_percent','系统内存 %'],['io_wait_percent','IO Wait %']]],
    ['memory','GPU 显存 / 字节',resourceRows,'sample',[['gpu_used_bytes','显存字节']]],
  ];
  return definitions.flatMap(([key,title,data,xKey,allFields])=>{
    const fields=allFields.filter(([field])=>data.some(row=>finite(row[field])!==null));
    if(!fields.length)return [];
    return [{key,title,rows:data,fields,xKey,options:{
      animation:false,aria:{enabled:true},tooltip:{trigger:'axis',axisPointer:{type:'cross'},confine:true,position:reportTooltipPosition},
      legend:{type:'scroll',top:4},grid:{left:55,right:26,top:55,bottom:70},
      xAxis:{type:'category',name:xKey==='epoch'?'Epoch':'采样序号',boundaryGap:false,data:data.map(row=>row[xKey])},
      yAxis:{type:'value',scale:true,...(fields.every(row=>row[2])?{min:0,max:1}:{})},
      dataZoom:[{type:'inside',filterMode:'none'},{type:'slider',bottom:12,height:20,filterMode:'none'}],
      series:fields.map(([field,name])=>({id:field,name,type:'line',connectNulls:false,showSymbol:data.length<100,symbolSize:5,data:data.map(row=>finite(row[field]))})),
    }}];
  });
}

let echartsLoad=null;
const reportCharts=new Map();
const reportInteractions=new Map();
export async function mountReportCharts(root,history=[],samples=[]) {
  if(!root?.isConnected)return;
  let owned=reportCharts.get(root);
  if(!owned){owned={charts:new Map(),groups:[],disposed:false};reportCharts.set(root,owned)}
  owned.groups=trainingChartGroups(history,samples);
  try{
    echartsLoad??=import('../vendor/echarts/echarts.min.js').then(()=>globalThis.echarts).catch(error=>{echartsLoad=null;throw error});
    const echarts=await echartsLoad;
    if(owned.disposed||!root.isConnected)return;
    const update=()=>{
      if(owned.disposed||!root.isConnected)return;
      for(const group of owned.groups){
        const host=root.querySelector(`[data-report-chart="${group.key}"]`);
        if(!host||!host.clientWidth)continue;
        let entry=owned.charts.get(group.key);
        if(entry&&entry.host!==host){entry.instance.dispose();owned.charts.delete(group.key);entry=null}
        if(!entry){entry={host,instance:echarts.init(host,null,{renderer:'canvas'}),signature:''};owned.charts.set(group.key,entry)}
        const signature=JSON.stringify(group.options);
        if(signature!==entry.signature){
          const style=getComputedStyle(root),text=style.color||'#334155';
          entry.instance.setOption({...group.options,textStyle:{color:text},backgroundColor:'transparent'});
          entry.signature=signature;
        }
        entry.instance.resize();
      }
      for(const [key,entry] of owned.charts)if(!root.contains(entry.host)){entry.instance.dispose();owned.charts.delete(key)}
    };
    if(!owned.observer&&typeof ResizeObserver!=='undefined')owned.observer=new ResizeObserver(update);
    root.querySelectorAll('[data-report-chart]').forEach(host=>owned.observer?.observe(host));
    update();
  }catch(error){
    if(owned.disposed||!root.isConnected)return;
    root.querySelectorAll('[data-chart-fallback]').forEach(node=>node.hidden=false);
    root.querySelectorAll('[data-report-chart]').forEach(node=>{node.textContent='交互图表加载失败，以下保留真实静态曲线';node.style.height='auto'});
  }
}
export function disposeReportViews(container) {
  for(const [root,owned] of reportCharts)if(!root.isConnected||root===container||container?.contains(root)){
    owned.disposed=true;owned.observer?.disconnect();for(const entry of owned.charts.values())entry.instance.dispose();reportCharts.delete(root);
  }
  for(const [root,controller] of reportInteractions)if(!root.isConnected||root===container||container?.contains(root)){controller.abort();reportInteractions.delete(root)}
}

function reportMetricCard(label,value){const n=finite(value);return `<div><span>${escapeText(label)}</span><b>${n===null?'未记录':(n*100).toFixed(1)+'%'}</b></div>`}
function frozenReportEvidenceHtml(report) {
  const quality=report.frozen_data_quality,id=report.identity||{},gate=report.data_summary?.quality_gate||{};
  const stage=gate.eval_interval?`<section class="report429-card"><header><b>训练阶段质量检查（非独立 Test）</b></header><p>每 ${escapeText(gate.eval_interval)} 轮检查 · 每次随机试验样本 ${escapeText(gate.stage_eval_samples??'未记录')} 张 · ${escapeText(gate.metric||'未记录')}</p>${(report.gate_events||[]).map(row=>`<p>Epoch ${escapeText(row.epoch)} · ${escapeText(row.metric)} ${escapeText(analysisValue(row.value))} · ${escapeText(row.decision)}</p>`).join('')}</section>`:'';
  const download=id.project_id&&id.algorithm_id&&id.version_id&&report.artifact_verified
    ? `<a class="btn" href="/api/v12/projects/${encodeURIComponent(id.project_id)}/algorithms/${encodeURIComponent(id.algorithm_id)}/versions/${encodeURIComponent(id.version_id)}/download">下载有效版本模型</a>`:'';
  return `${stage}<section class="report429-card"><header><b>冻结数据质量</b><button class="btn" data-report-data>核查正式素材与标注</button></header>${quality?`<p>${escapeText(quality.image_count??'未记录')} 张冻结图片 · 重复 ${escapeText(quality.duplicate_count??'未记录')} 张</p><div class="table-wrap"><table class="table"><thead><tr><th>类别</th><th>正样本图片</th><th>GT框</th></tr></thead><tbody>${(quality.classes||[]).slice(0,1000).map(row=>`<tr><td>${escapeText(row.label)}</td><td>${escapeText(row.image_count??'未记录')}</td><td>${escapeText(row.box_count??'未记录')}</td></tr>`).join('')}</tbody></table></div>`:'<p>未记录可信冻结数据分布，不使用当前素材代替历史证据。</p>'}</section><section class="report429-card"><header><b>模型成果</b>${download}</header><p>${(report.artifacts||[]).map(row=>escapeText(String(typeof row==='string'?row:row.file_name||row.filename||row.path||'未记录').split(/[\\/]/).pop())).join(' · ')||'未记录模型成果'}</p></section>${report.quality_analysis?.findings?.length?`<details class="report429-card"><summary>已记录曲线诊断（趋势信号，非根因定论）</summary>${report.quality_analysis.findings.map(row=>`<p><b>${escapeText(row.phenomenon)}</b> · ${escapeText(row.evidence_summary)}<br>${escapeText(row.action)}</p>`).join('')}</details>`:''}`;
}

export function trainingReportHtml({job={},report={}}={}) {
  report=currentReportFacts({job,report});
  const id=report.identity||{},actual=report.actual_train_params||{},metrics=report.metrics||{},evaluation=report.evaluation||{},errors=report.representative_errors||{};
  const metric=(key,alias)=>analysisMetric(metrics,key,[alias]);
  const kv=(label,value)=>`<div class="report-fact"><small>${escapeText(label)}</small><b>${escapeText(analysisValue(value))}</b></div>`;
  const count=report.data_summary?.counts||report.dataset_counts||{};
  const samples=(errors.items||[]).slice(0,12);
  const previewUrl=row=>`/api/v12/projects/${encodeURIComponent(id.project_id)}/algorithms/${encodeURIComponent(id.algorithm_id)}/versions/${encodeURIComponent(id.version_id)}/evaluation/images/${encodeURIComponent(row.image)}?${new URLSearchParams({expected_evaluation_id:errors.evaluation_id||'',expected_image_id:row.image_id||'',expected_sha256:row.image_content_sha256||''})}`;
  return `<div class="report429 quality-workspace training-report-workspace" data-report-job="${escapeText(id.job_id||job.id||'')}" data-report-version="${escapeText(id.version_id||'')}">
    <header class="quality-workspace-head"><div><span>TRAINING REPORT · ${escapeText(report.status||job.status||'状态未记录')}</span><h2>${escapeText(id.algorithm_name||'训练报告')} <small>${escapeText(report.version_name||id.version_id||'版本未记录')}</small></h2><p>任务 ${escapeText(id.job_id||'未记录')} · 模型 ${escapeText(report.model_architecture||'架构未记录')}</p></div><div class="report-primary-actions"><button class="btn primary" data-report-copy>复制 ChatGPT 分析材料</button><button class="btn" data-report-evaluation>查看独立评测</button></div></header>
    <div class="quality-metrics report-primary-metrics">${reportMetricCard('Validation Precision',metric('precision','metrics/precision(B)'))}${reportMetricCard('Validation Recall',metric('recall','metrics/recall(B)'))}${reportMetricCard('Val mAP50',metric('map50','metrics/mAP50(B)'))}${reportMetricCard('Val mAP50-95',metric('map5095','metrics/mAP50-95(B)'))}${kv('实际完成 / 请求Epoch',`${report.completed_epochs??'未记录'} / ${report.requested_train_params?.epochs??'未记录'}`)}${kv('真实最佳Checkpoint Epoch',report.best_epoch)}</div>
    <div class="report-status-row"><span>模型成果：${report.artifact_verified?'已验证归档':'验证未记录'}</span><span>独立 Test：${evaluation.status==='succeeded'?'已完成':'未完成或未记录'}</span><span>业务验收：未记录</span><span>结束原因：${escapeText(report.completion_reason||'未记录')}</span></div>
    ${report.note?`<p class="item-sub">${escapeText(report.note)}</p>`:''}
    <nav class="quality-tabs" role="tablist" aria-label="训练报告视图">${[['overview','概览'],['curves','训练曲线'],['errors','异常样本'],['provenance','数据与溯源']].map(([key,title])=>`<button class="btn" role="tab" data-report-tab="${key}" aria-selected="${key==='overview'}">${title}</button>`).join('')}</nav>
    <section data-report-pane="overview"><section class="report429-card"><div class="report425-facts">${kv('最大轮次',report.requested_train_params?.epochs)}${kv('实际轮次',report.completed_epochs)}${kv('停止原因',report.completion_reason==='quality_target_reached'?'达到目标指标，提前完成':report.completion_reason)}${kv('训练停止目标状态',report.completion_reason==='quality_target_reached'?'已达标':'未确认')}</div></section><div class="report-facts-grid">${kv('实际训练精度',actual.effective_precision??actual.precision)}${kv('实际输入尺寸',actual.imgsz)}${kv('Train / Val / Test图片',`${count.train??'未记录'} / ${count.validation??count.val??'未记录'} / ${count.test??'未记录'}`)}${kv('实际Batch / Workers',`${actual.batch??'未记录'} / ${actual.workers??'未记录'}`)}</div>${metricCredibilityHtml(report.metric_credibility)}<section class="report429-card"><header><b>结果解读边界</b></header><p>训练成功、模型精度与实际业务可用是不同事实。Validation 指标不代表独立 Test 或业务验收；请结合冻结证据和现场要求判断。</p><button class="btn" data-report-scenario>场景算法实测</button></section></section>
    <section data-report-pane="curves" hidden>${trainingCharts(report.history||[],report.runtime_metrics?.samples||[])}</section>
    <section data-report-pane="errors" hidden><section class="evaluation429-gallery report429-card"><header><b>代表性异常样本</b><span>已记录 ${errors.total_error_samples??errors.recorded_candidates??'未知'} 张异常，展示 ${samples.length} 张冻结引用</span></header><div class="evaluation429-gallery-bar"></div><div class="evaluation429-image-grid">${samples.map((row,index)=>`<article class="evaluation429-image-card" data-report-error="${index}" tabindex="0" role="button" aria-label="查看异常样本${index+1}" data-eval-url="${escapeText(previewUrl(row))}" data-eval-image="${escapeText(row.image)}" data-eval-width="${escapeText(row.image_width||'')}" data-eval-height="${escapeText(row.image_height||'')}"><span class="evaluation429-thumb"><img alt="冻结异常样本${index+1}" hidden><span class="evaluation429-thumb-status" data-eval-thumb-status>打开区域后按需读取</span></span><div class="evaluation429-card-title"><b>样本 ${index+1}</b><span data-eval-thumb-state>待读取</span></div><small data-eval-thumb-format></small><div class="evaluation429-counts"><i>FP ${row.fp_count}</i><i>FN ${row.fn_count}</i></div><p>${escapeText([...(row.fp_labels||[]),...(row.fn_labels||[])].join(' / '))}</p><small>GT ${row.boxes_truncated?'未完整记录':row.gt_boxes?.length??'未记录'} · 预测 ${row.boxes_truncated?'未完整记录':row.pred_boxes?.length??'未记录'}</small></article>`).join('')||`<p class="quality-empty">${escapeText(errors.reason||'未记录可信的冻结异常图片；训练错误不等于检测错误样本。')}</p>`}</div><p class="item-sub">只读冻结 Test 证据，未复制原图。图片不可用时不展示检测框；按权限手动附图给 ChatGPT。</p></section></section>
    <section data-report-pane="provenance" hidden><div class="report-facts-grid">${kv('Dataset Revision',report.dataset_revision_id)}${kv('Snapshot',report.snapshot_id)}${kv('母版本',report.base_version_name||report.base_version_id)}${kv('框架与模型',`${report.framework||'未记录'} / ${report.model_architecture||'未记录'}`)}</div><section class="report429-card"><header><b>请求 → 实际运行</b></header><div class="table-wrap"><table class="table"><thead><tr><th>参数</th><th>请求</th><th>实际</th></tr></thead><tbody>${['imgsz','precision','batch','workers','optimizer','lr0'].map(key=>`<tr><td>${key}</td><td>${escapeText(analysisValue(report.requested_train_params?.[key]))}</td><td>${escapeText(analysisValue(key==='optimizer'?report.runtime_metrics?.runtime_optimizer:key==='lr0'?report.runtime_metrics?.runtime_initial_learning_rates:key==='precision'?actual.effective_precision??actual.precision:actual[key]))}</td></tr>`).join('')}</tbody></table></div></section>${frozenReportEvidenceHtml(report)}<details><summary>完整技术证据与冻结合同</summary><pre class="log report-technical">${escapeText(JSON.stringify(report,null,2))}</pre></details></section>
    <details class="report429-card report-supplements"><summary>补充实际场景（可选）</summary><p class="item-sub">用户提供的现场描述，尚未由训练系统独立验证。</p><div class="form two">${[['scenario','实际业务场景与摄像头环境'],['target','期望指标与可接受误报漏报'],['observed','现场已观察问题'],['deployment','计划硬件、分析频率与性能要求']].map(([key,title])=>`<label class="field"><span>${title}</span><textarea class="input" rows="2" maxlength="2000" data-report-supplement="${key}"></textarea></label>`).join('')}</div></details>
    <details class="report429-card" data-report-analysis-preview><summary>预览完整 ChatGPT 分析材料</summary><textarea class="input report-analysis-text" readonly aria-label="ChatGPT分析材料"></textarea></details><p class="item-sub" data-report-copy-status role="status">本地确定性组装，不调用 AI，不上传图片或报告。</p>
  </div>`;
}
export function mountTrainingReport(root,response,{notify,onEvaluation,onSample,onData,onScenario,isCurrent=()=>root.isConnected}={}) {
  reportInteractions.get(root)?.abort();const controller=new AbortController();reportInteractions.set(root,controller);
  const {signal}=controller,report=response.report||{};
  const material=()=>chatGPTAnalysisMaterial(response,Object.fromEntries([...root.querySelectorAll('[data-report-supplement]')].map(node=>[node.dataset.reportSupplement,node.value])));
  const preview=()=>{const area=root.querySelector('.report-analysis-text');area.value=material();return area};
  root.addEventListener('toggle',event=>{if(event.target.matches('[data-report-analysis-preview]')&&event.target.open)preview()},{capture:true,signal});
  root.addEventListener('input',event=>{if(event.target.matches('[data-report-supplement]')&&root.querySelector('[data-report-analysis-preview]').open)preview()},{signal});
  root.addEventListener('click',async event=>{
    if(!isCurrent())return;
    const tab=event.target.closest('[data-report-tab]');
    if(tab){
      root.querySelectorAll('[data-report-tab]').forEach(node=>node.setAttribute('aria-selected',String(node===tab)));
      root.querySelectorAll('[data-report-pane]').forEach(node=>node.hidden=node.dataset.reportPane!==tab.dataset.reportTab);
      if(tab.dataset.reportTab==='curves')void mountReportCharts(root,report.history||[],report.runtime_metrics?.samples||[]);
      if(tab.dataset.reportTab==='errors')globalThis.window?.hydrateEvaluationGallery429?.(isCurrent,root);
      return;
    }
    if(event.target.closest('[data-report-scenario]')){onScenario?.();return}
    if(event.target.closest('[data-report-data]')){onData?.();return}
    if(event.target.closest('[data-report-evaluation]')){onEvaluation?.();return}
    const sample=event.target.closest('[data-report-error]');if(sample){onSample?.((report.representative_errors?.items||[])[Number(sample.dataset.reportError)]);return}
    const button=event.target.closest('[data-report-copy]');if(!button||button.disabled)return;
    button.disabled=true;const status=root.querySelector('[data-report-copy-status]');
    try{const text=material();if(!globalThis.navigator?.clipboard?.writeText)throw new Error('浏览器未提供安全剪贴板');await navigator.clipboard.writeText(text);if(isCurrent())status.textContent='已复制 ChatGPT 分析材料；需要分析图片时请手动附上允许外传的代表性异常图片。'}
    catch(error){if(isCurrent()){root.querySelector('[data-report-analysis-preview]').open=true;preview().select();status.textContent=`复制失败：${error.message}。可在上方预览中手动复制。`}}
    finally{if(root.isConnected)button.disabled=false}
  },{signal});
  root.addEventListener('keydown',event=>{const tab=event.target.closest('[data-report-tab]');if(tab&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const tabs=[...root.querySelectorAll('[data-report-tab]')],i=tabs.indexOf(tab),next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();tabs[next].click();return}const card=event.target.closest('[data-report-error]');if(card&&['Enter',' '].includes(event.key)){event.preventDefault();card.click()}},{signal});
}


export function lineageReportHtml({algorithm={},version={}}={}) {
  const lineage=version.training_lineage||{},execution=lineage.execution||{},params=lineage.parameters||{},base=lineage.base||{};
  const fact=(label,value)=>`<div class="report-fact"><small>${escapeText(label)}</small><b>${escapeText(analysisValue(value))}</b></div>`;
  return `<div class="report429 lineage429 training-lineage-workspace"><header class="quality-workspace-head"><div><span>TRAINING LINEAGE · 冻结版本事实</span><h2>${escapeText(algorithm.name||'算法')} <small>${escapeText(version.version_name||version.id||'')}</small></h2><p>版本迭代与断点续训分别保留原始合同，当前配置不改写历史。</p></div></header><div class="report-facts-grid">${fact('训练框架',lineage.framework)}${fact('实际精度',params.actual?.effective_precision??params.actual?.precision)}${fact('实际训练尺寸',params.actual?.imgsz)}${fact('实际设备',execution.actual_device)}</div><section class="report429-card"><header><b>母模型 → 当前版本</b></header><div class="report-facts-grid">${fact('来源版本',base.version_name||base.version_id)}${fact('母模型',String(base.model||'').split(/[\\/]/).pop())}${fact('训练任务',lineage.task_id)}${fact('Worker / 节点',[execution.worker_id,execution.node_id].filter(Boolean))}</div></section><section class="report429-card"><header><b>数据与冻结身份</b></header><div class="report-facts-grid">${fact('数据版本 Dataset Revision',lineage.dataset_revision_id)}${fact('Snapshot',lineage.snapshot_id)}</div></section><section class="report429-card"><header><b>模型产物</b><span>${(lineage.artifacts||[]).length} 个已记录成果</span></header><div class="table-wrap"><table class="table"><thead><tr><th>角色</th><th>文件</th><th>SHA256</th><th>大小 / 字节</th></tr></thead><tbody>${(lineage.artifacts||[]).map(row=>`<tr><td>${escapeText(row.role||'未记录')}</td><td>${escapeText(row.file_name||row.model_name||'未记录')}</td><td class="report-hash">${escapeText(row.sha256||'未记录')}</td><td>${row.size_bytes??'未记录'}</td></tr>`).join('')||'<tr><td colspan="4">未记录已验证成果</td></tr>'}</tbody></table></div></section><details class="report429-card"><summary>实际训练参数 / 请求参数与完整技术证据</summary><pre class="log report-technical">${escapeText(JSON.stringify(lineage,null,2))}</pre></details></div>`;
}
