import {loadLocalUppy} from './uppy-zip-adapter.js';
import {withRequestDeadline} from './api.js';

// Only the image transport owner creates requests and task records.
export async function mountImageUppyView({target, runtime, projectId, getProjectId, storageSourceId = 'default_local', retryNames = null, beforeConfirmation = null, loadUppy = loadLocalUppy, loadTimeoutMs = 30000, onEvent = () => {}, onFallback = () => {}}) {
  let uppy, running = false, destroyed = false, observer;
  const current = () => !destroyed && target?.isConnected !== false && !target?.closest?.('.modal')?.classList?.contains('hidden') && String(getProjectId()) === String(projectId);
  const destroy = () => { destroyed = true; observer?.disconnect(); if (!running) uppy?.destroy(); };
  try {
    const {Uppy, Dashboard, zhCN} = await withRequestDeadline(() => loadUppy(target), {timeoutMs:loadTimeoutMs, label:'图片上传界面加载'});
    if (!current()) return {destroy, uppy:null};
    uppy = new Uppy({autoProceed:false, allowMultipleUploadBatches:false, restrictions:{allowedFileTypes:['image/*']}, locale:zhCN, onBeforeFileAdded:file => {
      if (!retryNames || retryNames.includes(file.name)) return file;
      uppy?.info('本次仅允许重试已确认失败的文件，请核对文件名', 'error', 5000); return false;
    }});
    uppy.setState({capabilities:{...uppy.getState().capabilities, individualCancellation:false, uploadProgress:false, resumableUploads:false}});
    target.replaceChildren();
    uppy.use(Dashboard, {inline:true, target, width:'100%', height:390, proudlyDisplayPoweredByUppy:false, hideCancelButton:true, hideRetryButton:true, showRemoveButtonAfterComplete:false, note:'图片按批次传输；单张状态以服务器入库结果为准。关闭窗口后上传继续。'});
    uppy.addUploader(async ids => {
      if (running) return;
      if (!current()) throw new Error('项目已切换，请重新打开图片上传');
      running = true;
      const selected = ids.map(id => uppy.getFile(id)).filter(Boolean);
      uppy.setOptions({allowNewUpload:false});
      uppy.emit('upload-start', selected);
      const terminal = (file, error) => {
        if (!current() || !uppy.getFile(file.id)) return;
        if (error) uppy.emit('upload-error', file, new Error(error));
        else uppy.emit('upload-success', file, {status:200, body:{stored:true}});
      };
      try {
        await runtime.uploadFiles(selected.map(file => file.data), {storageSourceId, externalView:true, beforeConfirmation,
          onEvent: event => { if (current()) onEvent(event); },
          onCommitted: event => {
            const chunk = selected.filter(file => event.files.includes(file.data));
            const successful = [...(event.response?.uploaded || [])];
            const failed = [...(event.response?.failed || [])];
            for (const file of chunk) {
              const bad = failed.findIndex(row => String(row.name || row.filename) === file.name);
              if (bad >= 0) terminal(file, String(failed.splice(bad,1)[0].reason || '入库失败'));
              else {
                const good = successful.findIndex(row => String(row.filename || row.name) === file.name);
                if (good >= 0) { successful.splice(good,1); terminal(file); }
                else terminal(file, '服务器已返回批次结果，但未能匹配此文件；请查看上传确认页');
              }
            }
          },
        });
      } catch (error) {
        for (const file of selected) if (!uppy.getFile(file.id)?.progress?.uploadComplete && !uppy.getFile(file.id)?.error) terminal(file, error.message || '结果尚未确认，请从上传批次恢复');
      } finally {
        running = false;
        if (destroyed || !current()) uppy.destroy();
      }
    });
    const Observer = target?.ownerDocument?.defaultView?.MutationObserver || globalThis.MutationObserver;
    if (Observer && target?.ownerDocument?.body) {
      observer = new Observer(() => { if (!current()) destroy(); });
      observer.observe(target.ownerDocument.body, {childList:true, subtree:true, attributes:true, attributeFilter:['class']});
    }
    return {uppy, destroy};
  } catch (error) { if (current()) onFallback(error); destroy(); return {uppy:null, destroy}; }
}

export function installImageUppyView({getProjectId = () => window.S?.project?.id} = {}) {
  const api = {get uppy() { return api.handle?.uppy || null; }, async open({projectId = getProjectId(), storageSourceId = document.getElementById('uploadStorage61')?.value || 'default_local', retryNames = null} = {}) {
    if (!projectId || !window.MaterialUploadRuntime) { window.toast?.('当前项目或图片上传服务尚未就绪'); return null; }
    api.handle?.destroy();
    const chooser=document.getElementById('uploadStorage61')?.closest('.modal'),top=[...document.querySelectorAll('.modal:not(.hidden)')].at(-1);
    if(chooser&&chooser===top)window.closeModal?.();
    window.modal('上传图片', '<div data-image-uppy-view><div data-image-uppy-target><div class="loading">正在加载图片上传界面…</div></div><div class="item-sub" data-image-uppy-counts>选择图片后开始上传</div><button class="btn" data-image-uppy-close>关闭 · 后台继续</button></div>', true);
    const root = [...document.querySelectorAll('[data-image-uppy-view]')].at(-1);
    const target = root.querySelector('[data-image-uppy-target]');
    root.querySelector('[data-image-uppy-close]').onclick = () => { api.handle?.destroy(); window.closeModal?.(); };
    api.handle = await mountImageUppyView({target, runtime:window.MaterialUploadRuntime, projectId, getProjectId, storageSourceId, retryNames,
      beforeConfirmation:() => {
        const layer = root.closest('.modal');
        const top = [...document.querySelectorAll('.modal:not(.hidden)')].at(-1);
        if (!root.isConnected || !layer || layer.classList.contains('hidden') || top !== layer || String(getProjectId()) !== String(projectId)) return false;
        window.closeModal?.(); return true;
      },
      onEvent:event => {
        const counts = root.querySelector('[data-image-uppy-counts]');
        counts.textContent = `共 ${event.totalFiles} 张 · 已确认 ${event.confirmedFiles} · 成功 ${event.uploadedCount} · 失败 ${event.failedCount}` + (event.type === 'transfer' ? ` · 当前批 ${Math.round(event.loadedBytes / 1024)} / ${Math.round(event.totalBytes / 1024)} KB` : '');
      },
      onFallback:() => {
        target.innerHTML = '<label>选择图片<input type="file" accept="image/*" multiple></label><button class="btn primary">开始上传</button>';
        target.querySelector('button').onclick = () => {
          if (String(getProjectId()) !== String(projectId)) return window.toast?.('项目已切换，请重新打开上传');
          const files = Array.from(target.querySelector('input').files);
          if (retryNames && files.some(file => !retryNames.includes(file.name))) return window.toast?.('本次仅允许重试已确认失败的文件，请核对文件名');
          window.MaterialUploadRuntime.uploadFiles(files, {storageSourceId}).catch(error => window.toast?.(error.message));
        };
      },
    });
    return api.handle;
  }};
  window.ImageUppyView = api;
  window.chooseUploadImages426 = () => api.open();
  return api;
}
