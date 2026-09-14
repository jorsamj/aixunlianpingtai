from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


# 1) v61 deployment business projection reuses the unified durable public truth.
path = Path("app.py")
text = path.read_text(encoding="utf-8")
pattern = re.compile(
    r"def public_deployment_test\(task: TaskRecord\) -> Dict\[str, Any\]:\n.*?(?=\n\n@app\.)",
    re.S,
)
replacement = '''def public_deployment_test(task: TaskRecord) -> Dict[str, Any]:
    repository = shared_task_repository()
    truth = task_to_public(task, repository)
    result = shared_task_artifacts().read_json(task.task_id, task.result_ref, default={}) if task.result_ref else {}
    return {
        **truth,
        # v61 compatibility aliases remain for the existing deployment UI/API contract.
        "id": task.task_id,
        "progress": truth.get("progress_percent", task.progress),
        "stage": truth.get("phase", task.stage),
        "result": result or {},
    }
'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit(f"public_deployment_test patch: expected one match, got {count}")
path.write_text(text, encoding="utf-8")


# 2) Pure deployment-task view. It projects server truth; it never computes queue order/progress locally.
path = Path("static/modules/deployment-tests.js")
path.write_text(r'''import {isTaskActive, normalizeTaskStatus, taskProgress} from './task-poller.js';

function statusFallback(status) {
  return ({
    QUEUED: '排队中',
    WAITING_RESOURCE: '等待资源',
    PREPARING: '准备中',
    RUNNING: '测试中',
    PAUSING: '暂停中',
    PAUSED: '已暂停',
    RESUMING: '恢复中',
    CANCEL_REQUESTED: '取消中',
    RETRYING: '重试中',
    SUCCEEDED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
    BLOCKED_BY_ENVIRONMENT: '环境阻塞',
    BLOCKED_BY_HARDWARE: '硬件阻塞',
  })[status] || status || '-';
}

function positiveInteger(value) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : null;
}

export function deploymentTaskView(task = {}) {
  const status = normalizeTaskStatus(task.status);
  const progress = taskProgress(task);
  const queuePosition = positiveInteger(task.resource_queue_position);
  const waitReason = String(task.resource_wait_reason || '').trim();
  const workerId = String(task.worker_id || '').trim();
  const phase = String(task.phase ?? task.stage ?? '').trim();
  const currentItem = String(task.current_item || '').trim();
  const runtime = [];

  if ((status === 'QUEUED' || status === 'WAITING_RESOURCE') && queuePosition) {
    runtime.push(`资源队列第 ${queuePosition} 位`);
  }
  if (status === 'WAITING_RESOURCE' && waitReason) runtime.push(waitReason);
  if (status === 'RUNNING' && workerId) runtime.push(`Worker ${workerId}`);
  if (currentItem) runtime.push(currentItem);

  return {
    ...task,
    status,
    statusText: String(task.status_text || statusFallback(status)),
    percent: progress.percent,
    phase,
    runtimeText: runtime.join(' · '),
    active: isTaskActive(status),
  };
}
''', encoding="utf-8")


# 3) Expose deployment view through the existing PlatformCore and bump module cache.
path = Path("static/main.mjs")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "import {applyCleanConfirmation, cleanTaskView, isActiveCleanTask} from './modules/cleaning.js?v=422517';",
    "import {applyCleanConfirmation, cleanTaskView, isActiveCleanTask} from './modules/cleaning.js?v=422517';\nimport {deploymentTaskView} from './modules/deployment-tests.js?v=422518';",
    "main deployment import",
)
text = replace_once(
    text,
    "  cleaning: {applyCleanConfirmation, cleanTaskView, isActiveCleanTask},",
    "  cleaning: {applyCleanConfirmation, cleanTaskView, isActiveCleanTask},\n  deployment: {deploymentTaskView},",
    "main deployment PlatformCore",
)
path.write_text(text, encoding="utf-8")


# 4) Final deployment bench subscribes to unified durable truth while active.
path = Path("static/app.js")
text = path.read_text(encoding="utf-8")
pattern = re.compile(
    r"/\* Persistent deployment tests: upload returns immediately and a Worker performs real Runtime inference\. \*/\n"
    r"\(\(\)=>\{.*?\n\}\)\(\);\n\n"
    r"(?=/\* Activate the storage UI after every legacy compatibility layer has loaded\. \*/)",
    re.S,
)
replacement = r'''/* Persistent deployment tests: upload returns immediately and a Worker performs real Runtime inference. */
(()=>{
  const previousResult=window.renderDetectionResult;
  window.renderDetectionResult=function(result,title){
    const html=previousResult?.(result,title)||'',metrics=`<div class="report429-kpis"><div><span>预处理</span><b>${Number(result?.preprocess_ms||0).toFixed(2)} ms</b></div><div><span>模型推理</span><b>${Number(result?.inference_ms||0).toFixed(2)} ms</b></div><div><span>后处理</span><b>${Number(result?.postprocess_ms||0).toFixed(2)} ms</b></div><div><span>任务总耗时</span><b>${Number(result?.total_elapsed_ms||result?.elapsed_ms||0).toFixed(2)} ms</b></div></div>`;
    return html+metrics;
  };
  window.benchPredictOne=async function(selectId,file,conf){
    if(!file)throw new Error('请选择测试图片');const select=document.getElementById(selectId),model=(state.testModels||[])[Number(select?.value)];if(!model)throw new Error('请选择可用测试模型');
    const format=String(model.runtime_format||String(model.path||'').split('.').pop()||'').toLowerCase(),vendor=['rknn','om','bmodel'].includes(format),framework=model.framework||'ultralytics';
    const env=vendor?{}:(state.inferenceEnvs||[]).find(item=>item.framework===framework&&item.status==='ready');if(!vendor&&!env)throw new Error(`当前没有可用的${framework==='paddle'?'Paddle':'Ultralytics'} Runtime`);
    const form=new FormData();form.append('file',file);form.append('model_name',model.model_name||model.path||'');form.append('model_source',model.model_source||'project');form.append('local_path',model.path||'');form.append('algorithm_id',model.algorithm_id||'');form.append('version_id',model.version_id||'');form.append('conf',conf||.25);form.append('inference_framework',framework);form.append('inference_env_id',env?.id||'');
    let task=await api(`/api/v61/projects/${pid()}/deployment-tests`,{method:'POST',body:form}),attempt=0;const taskId=task.id||task.task_id;
    const active=()=>window.PlatformCore?.taskPoller?.isTaskActive?.(task.status)??['QUEUED','WAITING_RESOURCE','PREPARING','RUNNING','PAUSING','PAUSED','RESUMING','CANCEL_REQUESTED','RETRYING'].includes(String(task.status||'').toUpperCase());
    while(active()&&attempt++<700){
      const view=window.PlatformCore?.deployment?.deploymentTaskView?.(task)||{statusText:task.status,phase:task.phase||task.stage||'',percent:Number(task.progress_percent??task.progress??0),runtimeText:''};
      const output=document.getElementById('benchResult'),details=[view.statusText,view.runtimeText,view.phase,`${Number(view.percent||0).toFixed(1)}%`].filter(Boolean);
      if(output)output.innerHTML=`<div class="loading">真实 Runtime 测试中 · ${details.map(esc).join(' · ')}</div>`;
      await new Promise(resolve=>setTimeout(resolve,900));
      task=await api(`/api/v62/projects/${pid()}/tasks/${taskId}`);
    }
    if(task.status!=='SUCCEEDED')throw new Error(task.error||`部署测试未通过：${task.status}`);
    const completed=await api(`/api/v61/projects/${pid()}/deployment-tests/${taskId}`);
    return {r:completed.result||{},m:model,env};
  };
})();

'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit(f"final deployment layer patch: expected one match, got {count}")
path.write_text(text, encoding="utf-8")


# 5) Permanent behavior guard for deployment view truth.
path = Path("tests/frontend/deployment-task-view.test.mjs")
path.write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';
import {deploymentTaskView} from '../../static/modules/deployment-tests.js';


test('deployment task view preserves durable waiting-resource truth', () => {
  const view = deploymentTaskView({
    status: 'WAITING_RESOURCE',
    status_text: '等待资源',
    progress_percent: 17.5,
    phase: 'resource_waiting',
    resource_queue_position: 3,
    resource_wait_reason: 'DEPLOYMENT_RUNTIME_BUSY',
  });
  assert.equal(view.status, 'WAITING_RESOURCE');
  assert.equal(view.statusText, '等待资源');
  assert.equal(view.percent, 17.5);
  assert.equal(view.phase, 'resource_waiting');
  assert.equal(view.runtimeText, '资源队列第 3 位 · DEPLOYMENT_RUNTIME_BUSY');
  assert.equal(view.active, true);
});


test('deployment task view preserves worker and server progress while running', () => {
  const view = deploymentTaskView({
    status: 'RUNNING',
    progress_percent: 63,
    phase: 'inference',
    worker_id: 'deployment-worker-1',
    current_item: 'sample.jpg',
  });
  assert.equal(view.statusText, '测试中');
  assert.equal(view.percent, 63);
  assert.equal(view.runtimeText, 'Worker deployment-worker-1 · sample.jpg');
  assert.equal(view.active, true);
});
''', encoding="utf-8")


# 6) Browser cache bust only; formal VERSION remains untouched.
path = Path("static/index.html")
text = path.read_text(encoding="utf-8")
text = replace_once(text, "/static/app.js?v=42.25.96", "/static/app.js?v=42.25.97", "app cache")
text = replace_once(text, "/static/main.mjs?v=42.25.93", "/static/main.mjs?v=42.25.94", "main cache")
path.write_text(text, encoding="utf-8")

print("deployment durable queue/progress truth patch applied")
