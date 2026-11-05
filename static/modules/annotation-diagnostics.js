const escape = value => String(value ?? '未记录').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const list = value => Array.isArray(value) ? value.slice(0,100) : [];
export function diagnosticBoxes(diagnostics = {}, stage = 'final', finalBoxes = []) {
  const geometry = diagnostics.geometry || {}, contract = diagnostics.contract || {};
  let width = Number(geometry.original_width), height = Number(geometry.original_height);
  let boxes = list(stage === 'raw' ? diagnostics.raw_candidates : stage === 'converted' ? diagnostics.converted_boxes : finalBoxes);
  if(stage === 'raw') {
    if(contract.coordinate_space === 'normalized_1000') width = height = 1000;
    else if(contract.coordinate_space === 'normalized_01') width = height = 1;
    else if(contract.coordinate_space === 'pixel') {width = Number(geometry.inference_width); height = Number(geometry.inference_height);}
    else return [];
  }
  if(!(width > 0 && height > 0)) return [];
  return boxes.flatMap(box => {
    if(['x1','y1','x2','y2'].some(key => box[key] == null || box[key] === '')) return [];
    let [x1,y1,x2,y2] = ['x1','y1','x2','y2'].map(key => Number(box[key]));
    if(stage === 'raw' && contract.coordinate_order === 'yxyx') [x1,y1,x2,y2] = [y1,x1,y2,x2];
    if(![x1,y1,x2,y2].every(Number.isFinite) || x1 < 0 || y1 < 0 || x2 > width || y2 > height || x2 <= x1 || y2 <= y1) return [];
    return [{label:box.label, left:x1/width*100, top:y1/height*100, width:(x2-x1)/width*100, height:(y2-y1)/height*100}];
  });
}
export function renderAnnotationDiagnostics(d = {}, {imageUrl = '', finalBoxes = [], stage = 'final'} = {}) {
  const g = d.geometry || {}, c = d.contract || {}, counts = d.counts || {};
  const entries = [ ['模型',d.model_name || d.model],['适配器',d.provider || d.adapter],['配置版本',d.model_config_revision],['提示词版本',d.prompt_version],['耗时（ms）',d.latency_ms],['原图',g.original_width && g.original_height ? `${g.original_width} × ${g.original_height}` : null],['EXIF 方向',g.exif_orientation],['提交图像尺寸',(g.submitted_width || g.inference_width) && (g.submitted_height || g.inference_height) ? `${g.submitted_width || g.inference_width} × ${g.submitted_height || g.inference_height}` : null],['模型内部预处理',g.model_internal_geometry || '未记录'],['几何映射',g.mapping],['输出协议',c.output_protocol],['坐标合同',`${c.coordinate_space || '未记录'} / ${c.coordinate_order || '未记录'}`],['合同版本',c.coordinate_contract_version],['诊断状态',d.status], ...[['raw','原始候选'],['invalid','非法框'],['threshold_filtered','阈值淘汰'],['nms_filtered','NMS 淘汰'],['final','最终候选']].map(([key,name])=>[name,counts[key]]) ];
  const boxes = diagnosticBoxes(d, stage, finalBoxes);
  const raw = list(d.raw_candidates);
  return `<div class="row between"><b>标注诊断</b><button type="button" class="btn mini" data-diagnostic-close>收起</button></div><p class="item-sub" style="white-space:normal;overflow:visible;text-overflow:clip">${stage === 'raw' ? '原始位置按声明顺序换序后按声明范围显示；几何映射前的送模图像可能与原图不同。' : '框仅用于候选比对，不写入正式标注。'} MODEL_FALSE_POSITIVE（疑似误检）、MODEL_MISS（疑似漏检）、DISPLAY_TRANSFORM_ERROR（显示变换错误）需人工核查；未经校准的模型分数不代表准确率。</p><div class="row" role="group" aria-label="框位置对比">${[['raw','原始位置'],['converted','还原位置'],['final','最终结果']].map(([key,label])=>`<button type="button" class="btn mini ${stage===key?'primary':''}" aria-pressed="${stage===key}" data-diagnostic-stage="${key}">${label}</button>`).join('')}</div><div style="position:relative;width:100%;max-width:640px;margin-top:8px">${imageUrl ? `<img alt="诊断原图" src="${escape(imageUrl)}" style="display:block;width:100%;height:auto">` : '<p>原图不可用</p>'}${boxes.map(box=>`<span style="position:absolute;pointer-events:none;box-sizing:border-box;border:2px solid var(--primary,#165dff);left:${box.left}%;top:${box.top}%;width:${box.width}%;height:${box.height}%" title="${escape(box.label)}"></span>`).join('')}</div><p class="item-sub" style="white-space:normal;overflow:visible;text-overflow:clip">本视图显示 ${boxes.length} 个框；诊断最多保留 100 个结构化候选${d.raw_candidates_truncated?'（已截断）':''}。</p><dl style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px">${entries.map(([name,value])=>`<div style="min-width:0;overflow-wrap:anywhere"><dt class="item-sub">${escape(name)}</dt><dd style="margin:0">${escape(typeof value === 'object' ? '已记录' : value)}</dd></div>`).join('')}</dl><p class="item-sub" style="white-space:normal;overflow:visible;text-overflow:clip">结构化原始候选（字段顺序见坐标合同；仅当前图片，最多 100 条）</p><div style="overflow:auto;max-height:180px"><table class="table"><thead><tr><th>标签</th><th>x1,y1,x2,y2</th></tr></thead><tbody>${raw.map(box=>`<tr><td>${escape(box.label)}</td><td>${['x1','y1','x2','y2'].map(key=>escape(box[key])).join(', ')}</td></tr>`).join('') || '<tr><td colspan="2">无留存候选；历史任务可能没有诊断证据</td></tr>'}</tbody></table></div>`;
}
export function mountAnnotationDiagnostics(root, diagnostics, options) {
  const draw = stage => {
    root.innerHTML = renderAnnotationDiagnostics(diagnostics, {...options,stage});
    root.querySelector('[data-diagnostic-close]').onclick = () => root.remove();
    root.querySelectorAll('[data-diagnostic-stage]').forEach(button => button.onclick = () => draw(button.dataset.diagnosticStage));
  };
  draw('final');
}
