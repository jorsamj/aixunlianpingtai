from pathlib import Path

app_path = Path('static/app.js')
main_path = Path('static/main.mjs')
app = app_path.read_text(encoding='utf-8')
main = main_path.read_text(encoding='utf-8')

old_abort = """    let pollController=null;
    const taskKey=()=>`mc_server_material_import_${String(pid()||'default')}`;
    const getSavedTask=()=>{try{return localStorage.getItem(taskKey())||''}catch(_){return ''}};
    const saveTask=taskId=>{state.serverMaterialImportTaskId61=taskId||'';try{taskId?localStorage.setItem(taskKey(),taskId):localStorage.removeItem(taskKey())}catch(_){}};
    const abortPolling=()=>{if(pollController&&!pollController.signal.aborted)pollController.abort();pollController=null};
"""
new_abort = """    const taskKey=()=>`mc_server_material_import_${String(pid()||'default')}`;
    const getSavedTask=()=>{try{return localStorage.getItem(taskKey())||''}catch(_){return ''}};
    const saveTask=taskId=>{state.serverMaterialImportTaskId61=taskId||'';try{taskId?localStorage.setItem(taskKey(),taskId):localStorage.removeItem(taskKey())}catch(_){}};
    const abortPolling=()=>window.StorageImportProgressRuntime?.stop?.();
"""
assert old_abort in app, 'legacy storage import abort owner not found'
app = app.replace(old_abort, new_abort, 1)

old_poll = """    async function pollTask(taskId,initialTask){
      if(!taskId)return null;
      abortPolling();pollController=new AbortController();const signal=pollController.signal;
      try{return await serverApi().pollServerImport({initialTask,signal,load:()=>importRequest(taskUrl(taskId),{signal}),render:renderImportTask})}
      catch(error){if(!isAbort(error)){const status=document.getElementById('si61Status');if(status)status.innerHTML=`<div class=\"alert err\">${esc(error?.message||error||'导入任务读取失败')}</div>`}return null}
    }
"""
new_poll = """    window.renderStorageImportTask61=renderImportTask;

    async function pollTask(taskId,initialTask){
      if(!taskId)return null;
      try{
        const runtime=window.StorageImportProgressRuntime;
        if(!runtime?.track)throw new Error('素材导入进度模块未加载，请刷新页面后重试');
        return await runtime.track(taskId,initialTask);
      }
      catch(error){if(!isAbort(error)){const status=document.getElementById('si61Status');if(status)status.innerHTML=`<div class=\"alert err\">${esc(error?.message||error||'导入任务读取失败')}</div>`}return null}
    }
"""
assert old_poll in app, 'legacy storage import pollTask not found'
app = app.replace(old_poll, new_poll, 1)

old_open = '      abortPolling();pollController=new AbortController();\n      modal(\'从存储导入素材\','
assert old_open in app, 'legacy modal polling setup not found'
app = app.replace(old_open, "      abortPolling();\n      modal('从存储导入素材',", 1)
assert 'pollController' not in app, 'legacy storage pollController remains'
assert 'const runtime=window.StorageImportProgressRuntime;' in app, 'managed runtime lookup missing'
assert 'return await runtime.track(taskId,initialTask);' in app, 'managed track wiring missing'
assert 'StorageImportProgressRuntime?.stop' in app, 'managed stop wiring missing'

old_import = "import {buildServerImportRequest, buildImportConfirmation, pollServerImport, serverImportView} from './modules/server-material-import.js?v=422400';"
new_import = "import {buildServerImportRequest, buildImportConfirmation, serverImportView} from './modules/server-material-import.js?v=422520';"
assert old_import in main, 'server import main import not found'
main = main.replace(old_import, new_import, 1)
main = main.replace("import {installStorageImportProgressRuntime, storageImportProgressText} from './modules/storage-import-progress.js?v=422401';", "import {installStorageImportProgressRuntime, storageImportProgressText} from './modules/storage-import-progress.js?v=422520';", 1)

old_platform = '  serverMaterialImport: {buildServerImportRequest, buildImportConfirmation, pollServerImport, serverImportView},'
new_platform = '  serverMaterialImport: {buildServerImportRequest, buildImportConfirmation, serverImportView},'
assert old_platform in main, 'server import PlatformCore wiring not found'
main = main.replace(old_platform, new_platform, 1)

old_install = "installStorageImportProgressRuntime();\nwindow.installServerMaterialImport61?.();"
new_install = "window.installServerMaterialImport61?.();\nconst storageImportProgressRuntime = installStorageImportProgressRuntime({pollRegistry, getState: () => state});\nwindow.PlatformCore.runtime.storageImportProgressRuntime = storageImportProgressRuntime;"
assert old_install in main, 'storage import installation order not found'
main = main.replace(old_install, new_install, 1)

app_path.write_text(app, encoding='utf-8')
main_path.write_text(main, encoding='utf-8')
