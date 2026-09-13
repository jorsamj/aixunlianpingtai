from pathlib import Path

path = Path('static/app.js')
text = path.read_text(encoding='utf-8')
helper = "function mapImportProcessingProgress411(progress){const p=Math.max(0,Math.min(100,Number(progress)||0));return Math.min(99,Math.round((38+p*.61)*10)/10)}\n"
anchor = "  async function pollImport411(jobId){const start=performance.now();while(true){await new Promise(r=>setTimeout(r,450));let j;try{j=await api(`/api/v19/projects/${pid()}/import/jobs/${jobId}`)}catch(e){continue}let eta=j.eta_seconds;if(eta==null&&Number(j.progress)>2){const el=Math.max(.1,(performance.now()-start)/1000),p=Number(j.progress);eta=el/p*(100-p)}setImport411({stage:j.stage||'后台处理中',message:j.message||'',progress:Number(j.progress||0),processSeconds:j.processing_seconds??((performance.now()-start)/1000),eta});if(['done','failed'].includes(j.status))return j}}"
replacement = "  " + helper + "  async function pollImport411(jobId){const start=performance.now();while(true){await new Promise(r=>setTimeout(r,450));let j;try{j=await api(`/api/v19/projects/${pid()}/import/jobs/${jobId}`)}catch(e){continue}let eta=j.eta_seconds;if(eta==null&&Number(j.progress)>2){const el=Math.max(.1,(performance.now()-start)/1000),p=Number(j.progress);eta=el/p*(100-p)}setImport411({stage:j.stage||'后台处理中',message:j.message||'',progress:mapImportProcessingProgress411(j.progress),processSeconds:j.processing_seconds??((performance.now()-start)/1000),eta});if(['done','failed'].includes(j.status))return j}}"
if 'function mapImportProcessingProgress411(progress)' in text:
    raise SystemExit('migration already applied')
if anchor not in text:
    raise SystemExit('expected ZIP import polling anchor not found')
text = text.replace(anchor, replacement, 1)
path.write_text(text, encoding='utf-8')
