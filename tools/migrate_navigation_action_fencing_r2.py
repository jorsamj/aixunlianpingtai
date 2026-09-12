from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'static' / 'app.js'
INDEX = ROOT / 'static' / 'index.html'

app = APP.read_text(encoding='utf-8')


def replace_last_line(marker: str, replacement: str) -> None:
    global app
    start = app.rfind(marker)
    if start < 0:
        raise SystemExit(f'live owner not found: {marker}')
    line_end = app.find('\n', start)
    if line_end < 0:
        line_end = len(app)
    old = app[start:line_end]
    if '\n' in old:
        raise SystemExit(f'expected single-line owner: {marker}')
    app = app[:start] + replacement + app[line_end:]


replace_last_line(
    "window.saveVisionModelM4=async function(id='')",
    "window.saveVisionModelM4=async function(id=''){const action=window.NavigationStability?.action?.(state.page);const kind=document.getElementById('mcProviderAdapter')?.value||'local_openai',name=document.getElementById('mcName')?.value.trim()||'',model=document.getElementById('mcModel')?.value.trim()||'',url=document.getElementById('mcUrl')?.value.trim()||providerDefaults[kind]||'';if(!name||!model)return toast('请填写配置名称和模型名称');if(!url)return toast('请填写该服务所在地域对应的 Base URL');const body={name,provider_type:kind,provider_adapter:kind,model_kind:'vlm',base_url:url,detect_url:url,health_url:document.getElementById('mcHealth')?.value.trim()||'',model_name:model,api_key:document.getElementById('mcApiKey')?.value||'',annotation_prompt_template:document.getElementById('mcAnnPrompt')?.value||'',default_for_annotation:!!document.getElementById('mcDefaultAnn')?.checked,remark:document.getElementById('mcRemark')?.value||'',request_mode:'openai_vision',image_field:'image',prompt_field:'prompt'};try{const saved=await api(id?`/api/v35/model-configs/${id}`:'/api/v35/model-configs',{method:id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});if(action&&!action.isCurrent())return;if(saved?.id){const rows=state.modelConfigs||[],i=rows.findIndex(x=>String(x.id)===String(saved.id));state.modelConfigs=i>=0?rows.map((x,n)=>n===i?saved:x):[saved,...rows]}closeModal();renderModelConfigPageV35();toast('视觉模型配置已保存')}catch(e){if(action&&!action.isCurrent())return;toast(e.message||e)}};"
)

replace_last_line(
    'window.testModelConfigV35=async function(id)',
    "window.testModelConfigV35=async function(id){const action=window.NavigationStability?.action?.(state.page);try{const r=await api(`/api/v35/model-configs/${id}/test-annotation`,{method:'POST'});if(action&&!action.isCurrent())return;modal('模型连接与标注解析测试',`<div class=\"model-m4-test\"><div class=\"report429-kpis\"><div><span>连接</span><b>${r.reachable?'成功':'失败'}</b></div><div><span>提供商</span><b>${esc(providerNames[r.provider]||r.provider||'-')}</b></div><div><span>模型</span><b>${esc(r.model||'-')}</b></div><div><span>耗时</span><b>${Number(r.latency_ms||0)} ms</b></div></div><div class=\"alert ok\">成功解析 ${r.parsed_boxes?.length||0} 个候选框；本次测试不会写入任何图片标注。</div><details><summary>脱敏响应预览</summary><pre class=\"log small-log\">${esc(r.raw_preview||'')}</pre></details><div class=\"row end\"><button class=\"btn\" onclick=\"closeModal()\">关闭</button></div></div>`,true)}catch(e){if(action&&!action.isCurrent())return;toast(e.message||e)}};"
)

replace_last_line(
    'window.confirmClean429=async function(id)',
    "window.confirmClean429=async function(id){const action=window.NavigationStability?.action?.(state.page);try{const r=await api(`/api/v47/projects/${pid()}/clean-tasks/${id}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delete_ids:[...state.v427CleanConfirm]})});if(action&&!action.isCurrent())return;const del=new Set((r.deleted_ids||[]).map(String)),proc=new Set((r.processed_ids||[]).map(String));state.images=(state.images||[]).filter(x=>!del.has(String(x.id)));state.images.forEach(x=>{if(proc.has(String(x.id))){x.processing_status='processed';x.cleaned_at=new Date().toISOString()}});closeModal();if(state.page==='数据集')renderDatasets424();toast(`清洗确认完成：删除 ${r.deleted||0} 张，其余进入已处理`)}catch(e){if(action&&!action.isCurrent())return;toast(e.message||e)}};"
)

replace_last_line(
    'window.confirmAiLabel427=async function(id)',
    "window.confirmAiLabel427=async function(id){const action=window.NavigationStability?.action?.(state.page);try{const r=await api(`/api/v47/projects/${pid()}/ai-label-tasks/${id}/confirm`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_ids:[...state.v427AiConfirm]})});if(action&&!action.isCurrent())return;const cmap=new Map((state.ai429CandidateResult?.items||[]).map(x=>[String(x.image_id),x]));(r.applied_image_ids||[]).forEach(i=>{const img=(state.images||[]).find(x=>String(x.id)===String(i)),it=cmap.get(String(i));if(img&&it){img.annotated=(it.boxes||[]).length>0;img.box_count=(img.box_count||0)+(it.boxes||[]).length;img.labels=[...new Set([...(img.labels||[]),...(it.boxes||[]).map(b=>b.label).filter(Boolean)])]}});closeModal();if(state.page==='数据集')renderDatasets424();toast(`已确认 ${r.applied_images||0} 张，写入 ${r.boxes_added||0} 个框`)}catch(e){if(action&&!action.isCurrent())return;toast(e.message||e)}};"
)

APP.write_text(app, encoding='utf-8')

index = INDEX.read_text(encoding='utf-8')
old = '/static/app.js?v=42.25.88'
new = '/static/app.js?v=42.25.90'
if old not in index:
    raise SystemExit(f'expected app cache marker missing: {old}')
INDEX.write_text(index.replace(old, new, 1), encoding='utf-8')
