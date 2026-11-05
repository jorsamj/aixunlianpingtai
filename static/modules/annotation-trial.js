import {createAnnotoriousEditor} from './annotorious-editor.js?v=20261022a';
const clone = value => JSON.parse(JSON.stringify(value));
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// A disposable session: its only request is the read-only comparison endpoint.
export async function mountTrial(root, response, {labels, compareUrl, active, signal}) {
  const requests=new AbortController();
  const abort=()=>requests.abort();signal.addEventListener('abort',abort,{once:true});
  let baseline=clone(response.baseline?.boxes||[]).filter(b=>labels.some(l=>l.code===b.label)).map((b,i)=>({...b,id:String(b.id||`baseline-${i}`)}));
  const original=clone(baseline), predictions=clone(response.boxes||[]).map((b,i)=>({...b,id:String(b.id||`prediction-${i}`)}));
  let mode='baseline', selected=null, editor, history=[], disposed=false, sequence=0, report=null;
  const alive=()=>!disposed&&active()&&!signal.aborted;
  const shown=()=>mode==='original'?[]:mode==='prediction'?predictions:mode==='overlay'?[...baseline.map(b=>({...b,id:'base-'+b.id})),...predictions.map(b=>({...b,id:'ai-'+b.id}))]:baseline;
  root.innerHTML=`<p>${predictions.length} 个候选框 · ${esc(response.model)} · ${Number(response.latency_ms||0)}ms</p><div class="row"><button class="btn mini" data-view="original">原图</button><button class="btn mini" data-view="baseline">临时人工基准</button><button class="btn mini" data-view="prediction">AI 结果</button><button class="btn mini" data-view="overlay">叠加比对</button><button class="btn mini" data-action="copy">复制正式 GT 为基准</button><button class="btn mini" data-action="undo">撤销</button></div>
  <div class="row"><select class="select" data-label>${labels.map(l=>`<option value="${esc(l.code)}">${esc(l.display_name_zh||l.code)}</option>`).join('')}</select><button class="btn mini" data-action="draw">新增框</button><button class="btn mini" data-action="select">移动/缩放</button><button class="btn mini" data-action="delete">删除选中</button><button class="btn mini" data-action="relabel">修改标签</button><button class="btn mini" data-action="empty">确认本图无目标</button><button class="btn mini" data-action="pan">拖动视图</button><button class="btn mini" data-action="fit">适应</button><button class="btn mini" data-action="zoom">放大</button><label><input type="checkbox" data-visible checked>显示框</label></div>
  <div data-viewport style="position:relative;height:460px;overflow:hidden;background:var(--bg,#f5f7fa)"><div data-world style="position:absolute;transform-origin:0 0"><img data-image src="${esc(response.image.url)}" alt="试跑原图" draggable="false" style="display:block;max-width:none"></div></div>
  <p data-detail>临时基准仅保存在本次会话，编辑不会提交正式 GT。</p>
  <div class="row"><label><input type="checkbox" data-complete>我已确认基准完整（含无目标）</label><label>IoU <input data-threshold type="number" min="0.01" max="1" step="0.05" value="0.5" style="width:70px"></label><button class="btn" data-action="compare">对比差异</button><button class="btn" data-action="export">导出诊断摘要</button></div><pre data-report style="white-space:pre-wrap;max-height:260px;overflow:auto"></pre>`;
  const q=s=>root.querySelector(s), image=q('[data-image]'), detail=q('[data-detail]');
  const invalidate=()=>{report=null;++sequence;q('[data-report]').textContent='基准已变化，请重新对比。'};
  const change=next=>{history.push(clone(baseline));history=history.slice(-30);baseline=clone(next);invalidate();editor?.sync()};
  const setView=next=>{mode=next;editor?.sync({locked:mode!=='baseline'});detail.textContent=mode==='baseline'?'临时基准 · 仅本次会话':'只读视图'};
  try {
    editor=await createAnnotoriousEditor({image,viewport:q('[data-viewport]'),world:q('[data-world]'),width:response.image.width,height:response.image.height,signal,isActive:alive,
      getBoxes:shown,getLabels:()=>labels,getLabel:()=>q('[data-label]').value,
      onCommit:next=>change(next),onSelect:id=>{selected=id;detail.textContent=JSON.stringify(shown().find(b=>String(b.id)===String(id))||{});},onError:e=>{detail.textContent=e.message}});
    if(!alive()){editor.destroy();return ()=>{}};
    root.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
    q('[data-visible]').onchange=e=>editor.setVisibility(e.target.checked);
    q('[data-complete]').onchange=invalidate;q('[data-threshold]').oninput=invalidate;
    const actions={copy:()=>{setView('baseline');change(original)},undo:()=>{if(history.length){baseline=history.pop();invalidate();editor.sync()}},
      draw:()=>{setView('baseline');editor.setMode('draw')},select:()=>{editor.setMode('select')},pan:()=>editor.setMode('pan'),fit:()=>editor.fit(),zoom:()=>editor.zoom(.2),
      delete:()=>{if(mode==='baseline')editor.deleteSelected()},relabel:()=>{if(mode==='baseline')editor.reclassSelected(q('[data-label]').value)},
      empty:()=>{setView('baseline');change([]);q('[data-complete]').checked=true},
      compare:async()=>{editor.flush();const seq=++sequence;try{const res=await fetch(compareUrl,{method:'POST',headers:{'Content-Type':'application/json'},signal:requests.signal,body:JSON.stringify({baseline,predictions,image_width:response.image.width,complete:q('[data-complete]').checked,threshold:Number(q('[data-threshold]').value)})});if(!res.ok)throw new Error('差异计算失败，请检查坐标及 IoU 阈值');const result=await res.json();if(!alive()||seq!==sequence)return;report={image:response.image.id,label_scope:labels.map(l=>l.code),frontend:{view:mode,natural_width:image.naturalWidth,natural_height:image.naturalHeight,device_pixel_ratio:window.devicePixelRatio,image_rect:image.getBoundingClientRect().toJSON(),drawn_rects:[...root.querySelectorAll('.a9s-annotation[data-id]')].map(el=>el.getBoundingClientRect().toJSON())},model:response.model,diagnostics:response.diagnostics,baseline_count:baseline.length,prediction_count:predictions.length,...result};q('[data-report]').textContent=JSON.stringify(report,null,2)}catch(e){if(alive())q('[data-report]').textContent=e.message}},
      export:()=>{if(!report){detail.textContent='请先对比差异';return}const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='annotation-trial.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}};
    root.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>actions[b.dataset.action]?.());
  } catch(e){if(alive())detail.textContent=e.message;}
  return ()=>{disposed=true;++sequence;requests.abort();signal.removeEventListener('abort',abort);editor?.destroy()};
}
