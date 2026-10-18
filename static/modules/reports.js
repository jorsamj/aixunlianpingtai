export function reportPresentation(report = {}) {
  if (report.report_type === 'algorithm') {
    return {title: '算法综合训练报告', scope: 'algorithm'};
  }
  return {title: '单版本训练报告', scope: 'version'};
}

const escapeText = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const finite = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? Number(value) : null;

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

export function trainingCharts(history = []) {
  const rows=history.slice(-1000).map(row=>({epoch:row.epoch,
    box_loss:row.box_loss??row.losses?.box_loss??row.losses?.['train/box_loss'],
    cls_loss:row.cls_loss??row.losses?.cls_loss??row.losses?.['train/cls_loss'],
    dfl_loss:row.dfl_loss??row.losses?.dfl_loss??row.losses?.['train/dfl_loss'],
    val_box_loss:row.val_box_loss??row.metrics?.['val/box_loss'],
    precision:row.precision??row.metrics?.['metrics/precision(B)'],
    recall:row.recall??row.metrics?.['metrics/recall(B)'],
    map50:row.map50??row.metrics?.['metrics/mAP50(B)'],
    map5095:row.map5095??row.metrics?.['metrics/mAP50-95(B)'],
    learning_rate:row.learning_rate??row.learning_rates?.['lr/pg0'],
  }));
  const series=[
    ['map50','mAP50',true],['map5095','mAP50-95',true],['precision','Precision',true],['recall','Recall',true],
    ['box_loss','Train Box Loss'],['cls_loss','Train Class Loss'],['dfl_loss','Train DFL Loss'],
    ['val_box_loss','Validation Box Loss'],['learning_rate','Learning Rate'],
  ];
  const recorded=series.filter(([key])=>rows.some(row=>finite(row[key])!==null));
  if(!recorded.length)return '<div class="quality-empty">暂无训练曲线记录；不根据最终指标补造 Epoch 曲线。</div>';
  const missing=series.filter(([key])=>!recorded.some(item=>item[0]===key)).map(item=>item[1]);
  return `<div class="quality-chart-grid-layout">${recorded.map(([key,title,percent])=>metricChart(rows,key,title,{percent})).join('')}</div>${missing.length?`<p class="quality-chart-missing">未记录：${missing.map(escapeText).join('、')}</p>`:''}`;
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
