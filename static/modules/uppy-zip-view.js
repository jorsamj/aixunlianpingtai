// View entry only: the original ZIP controller and Modal Stack own execution.
import {mountUppyZipAdapter} from './uppy-zip-adapter.js';

export async function openUppyZipView({runtime=window.ZipImportRuntime,projectId=runtime?.getProjectId(),poc=false}={}){
  if(!runtime||!projectId){window.toast?.('项目或ZIP上传服务尚未就绪');return null;}
  window.ZipUppyView?.destroy?.();
  window.modal(poc?'ZIP 上传组件验证':'上传 ZIP',`<div data-uppy-zip-view><div class="alert soft">文件上传与后台导入分阶段执行。扫描完成后将自动进入标签确认；后台进度可从上传任务中心查看。</div><div data-uppy-zip-target role="region" aria-label="ZIP文件上传"><div class="loading">正在加载ZIP上传界面…</div></div><div class="row end"><button class="btn" data-uppy-use-legacy>使用原上传界面</button><button class="btn" onclick="closeModal()">关闭 · 后台继续</button></div><div data-uppy-legacy class="hidden"><label>选择ZIP文件（可多选）<input type="file" accept=".zip,application/zip" multiple data-uppy-legacy-input></label><button class="btn primary" data-uppy-legacy-submit>上传并扫描</button></div></div>`,true);
  const root=[...document.querySelectorAll('[data-uppy-zip-view]')].at(-1),target=root.querySelector('[data-uppy-zip-target]');
  let adapter=null,abandoned=false;
  const handle={get uppy(){return adapter?.uppy||null},destroy(){abandoned=true;adapter?.destroy()}};
  window.ZipUppyView=handle;
  runtime.registerUploadView?.({projectId,layer:root.closest?.('.modal'),onHandoff:()=>handle.destroy()});
  const legacy=()=>{
    abandoned=true;adapter?.destroy();target.replaceChildren();target.classList.add('hidden');
    root.querySelector('[data-uppy-legacy]').classList.remove('hidden');
    root.querySelector('[data-uppy-use-legacy]').hidden=true;
  };
  root.querySelector('[data-uppy-use-legacy]').onclick=legacy;
  root.querySelector('[data-uppy-legacy-submit]').onclick=()=>runtime.uploadBatch(root.querySelector('[data-uppy-legacy-input]')).catch(error=>window.toast?.(error.message||error));
  adapter=await mountUppyZipAdapter({target,runtime,projectId,onFallback:legacy,notify:message=>window.toast?.(message)});
  if(abandoned)adapter?.destroy();
  return handle;
}
