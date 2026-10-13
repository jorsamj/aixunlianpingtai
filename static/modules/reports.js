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
