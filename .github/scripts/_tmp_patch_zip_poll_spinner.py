from pathlib import Path

path = Path("static/app.js")
text = path.read_text(encoding="utf-8")

old_poll = """  function mapImportProcessingProgress411(progress){const p=Math.max(0,Math.min(100,Number(progress)||0));return Math.round((3800+p*61)/10)/10}\n  async function pollImport411(jobId){const start=performance.now();while(true){await new Promise(r=>setTimeout(r,450));let j;try{j=await api(`/api/v19/projects/${pid()}/import/jobs/${jobId}`)}catch(e){continue}let eta=j.eta_seconds;if(eta==null&&Number(j.progress)>2){const el=Math.max(.1,(performance.now()-start)/1000),p=Number(j.progress);eta=el/p*(100-p)}setImport411({stage:j.stage||'后台处理中',message:j.message||'',progress:mapImportProcessingProgress411(j.progress),processSeconds:j.processing_seconds??((performance.now()-start)/1000),eta});if(['done','failed'].includes(j.status))return j}}\n"""
new_poll = """  function mapImportProcessingProgress411(progress){const p=Math.max(0,Math.min(100,Number(progress)||0));return Math.round((3800+p*61)/10)/10}\n  function importPollFailureAction411(failures,code){if(String(code||'')==='HTTP_404')return 'missing';return Number(failures)>=12?'unavailable':'retry'}\n  async function pollImport411(jobId){const start=performance.now();let consecutiveErrors=0;while(true){await new Promise(r=>setTimeout(r,450));let j;try{j=await api(`/api/v19/projects/${pid()}/import/jobs/${jobId}`);consecutiveErrors=0}catch(e){consecutiveErrors++;const action=importPollFailureAction411(consecutiveErrors,e?.code);if(action==='retry')continue;const error=new Error(action==='missing'?'导入任务记录不存在，请刷新导入任务列表确认最终状态。':'连续无法读取导入进度，后台任务可能仍在执行。请关闭窗口后从“导入任务”重新查看。');error.code=action==='missing'?'IMPORT_POLL_MISSING':'IMPORT_POLL_UNAVAILABLE';throw error}let eta=j.eta_seconds;if(eta==null&&Number(j.progress)>2){const el=Math.max(.1,(performance.now()-start)/1000),p=Number(j.progress);eta=el/p*(100-p)}setImport411({stage:j.stage||'后台处理中',message:j.message||'',progress:mapImportProcessingProgress411(j.progress),processSeconds:j.processing_seconds??((performance.now()-start)/1000),eta});if(['done','failed'].includes(j.status))return j}}\n"""
if old_poll not in text:
    raise SystemExit("active ZIP polling snippet not found exactly")
text = text.replace(old_poll, new_poll, 1)

old_catch = """}catch(e){setImport411({stage:'导入失败',progress:100,eta:0,resultHtml:`<div class=\"alert err\">${esc(e.message||e)}</div>`})}};xhr.send(fd);inp.value='';\n"""
new_catch = """}catch(e){if(e?.code==='IMPORT_POLL_UNAVAILABLE'){setImport411({stage:'进度读取中断',message:e.message||'连续无法读取导入进度，后台任务可能仍在执行。',eta:null,resultHtml:`<div class=\"alert warn\"><b>进度读取中断</b>：${esc(e.message||'后台任务可能仍在执行，请稍后从“导入任务”重新查看。')}</div>`});toast(e.message||e);return}if(e?.code==='IMPORT_POLL_MISSING'){setImport411({stage:'导入状态异常',message:e.message||'导入任务记录不存在',eta:null,resultHtml:`<div class=\"alert warn\">${esc(e.message||'导入任务记录不存在，请刷新导入任务列表确认最终状态。')}</div>`});toast(e.message||e);return}setImport411({stage:'导入失败',progress:100,eta:0,resultHtml:`<div class=\"alert err\">${esc(e.message||e)}</div>`})}};xhr.send(fd);inp.value='';\n"""
if old_catch not in text:
    raise SystemExit("active ZIP outer catch snippet not found exactly")
text = text.replace(old_catch, new_catch, 1)

path.write_text(text, encoding="utf-8")
