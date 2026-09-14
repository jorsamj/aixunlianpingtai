from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


# 1) Pure clean-task view model: server status/progress/queue fields are authoritative.
path = Path("static/modules/cleaning.js")
path.write_text(r'''const ACTIVE_CLEAN = new Set(['queued', 'running']);

function cleanStatusFallback(status) {
  return ({
    queued: '排队中',
    running: '清洗中',
    awaiting_confirmation: '待确认',
    done: '已完成',
    failed: '失败',
    cancelled: '已停止',
    stopped: '已停止',
  })[status] || status || '-';
}

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function isActiveCleanTask(task) {
  const status = typeof task === 'string' ? task : task?.status;
  return ACTIVE_CLEAN.has(String(status || '').toLowerCase());
}

export function cleanTaskView(task = {}) {
  const status = String(task.status || '').toLowerCase();
  const statusText = String(task.status_text || cleanStatusFallback(status));
  const percent = Math.max(0, Math.min(100, finiteNumber(task.progress, 0)));
  const processed = Math.max(0, finiteNumber(task.processed_images, 0));
  const total = Math.max(0, finiteNumber(task.total_images, 0));
  const flagged = Math.max(0, finiteNumber(task.flagged_images, 0));
  const queuePosition = Math.max(0, Math.trunc(finiteNumber(task.resource_queue_position, 0)));
  const waitReason = String(task.resource_wait_reason || '').trim();
  const workerId = String(task.worker_id || '').trim();

  let runtimeText = '';
  if (status === 'queued') {
    const parts = [];
    if (queuePosition > 0) parts.push(`资源队列第 ${queuePosition} 位`);
    if (waitReason) parts.push(waitReason);
    runtimeText = parts.join(' · ');
  } else if (status === 'running' && workerId) {
    runtimeText = `Worker ${workerId}`;
  }

  return {
    ...task,
    status,
    statusText,
    percent,
    processed,
    total,
    flagged,
    progressText: `${processed}/${total}`,
    runtimeText,
    active: isActiveCleanTask(status),
  };
}

export function applyCleanConfirmation(materials, result) {
  const deleted = new Set((result?.deleted_images || result?.deleted_ids || []).map(String));
  const processed = new Set((result?.processed_ids || []).map(String));
  return (materials || [])
    .filter(material => !deleted.has(String(material.id)))
    .map(material => processed.has(String(material.id))
      ? {...material, processing_status: 'processed', clean_skipped: false}
      : material);
}
''', encoding="utf-8")


# 2) PollRegistry becomes the only clean-list timer owner.
path = Path("static/modules/poll-registry.js")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "  const videoOwner = '视频切帧';\n  const sourceOwner = '素材接入';\n",
    "  const videoOwner = '视频切帧';\n  const sourceOwner = '素材接入';\n  const cleanOwner = '自动标注及清洗';\n",
    "poll clean owner",
)
clean_functions = r'''
  function cleanTaskActive(task) {
    const helper = window.PlatformCore?.cleaning?.isActiveCleanTask;
    if (typeof helper === 'function') return Boolean(helper(task));
    return ['queued', 'running'].includes(String(task?.status || '').toLowerCase());
  }

  function replaceCleanTaskTimer() {
    const s = state();
    registry.clear('clean-tasks-v47');
    if (String(s.page || '') !== cleanOwner) return null;
    if (String(s.v427OpsTab || 'label') !== 'clean') return null;
    if (!(s.clean427 || []).some(cleanTaskActive)) return null;

    return registry.startTimeout(
      'clean-tasks-v47',
      cleanOwner,
      async () => {
        const current = state();
        if (String(current.page || '') !== cleanOwner) return;
        if (String(current.v427OpsTab || 'label') !== 'clean') return;
        if (!current.project?.id) return;
        if (typeof window.refreshCleanOps427Delta === 'function') {
          await window.refreshCleanOps427Delta();
        }
      },
      2200,
    );
  }

'''
text = replace_once(
    text,
    "  function replaceSourceTimer() {\n",
    clean_functions + "  function replaceSourceTimer() {\n",
    "poll clean functions",
)
text = replace_once(
    text,
    "    replaceVideo424Timer,\n    replaceSourceTimer,\n",
    "    replaceVideo424Timer,\n    replaceCleanTaskTimer,\n    replaceSourceTimer,\n",
    "poll clean runtime export",
)
text = replace_once(
    text,
    "  replaceVideo424Timer();\n  replaceSourceTimer();\n",
    "  replaceVideo424Timer();\n  replaceCleanTaskTimer();\n  replaceSourceTimer();\n",
    "poll clean initial ownership",
)
path.write_text(text, encoding="utf-8")


# 3) Expose the pure view/active helpers to legacy app.js wiring and bust module cache.
path = Path("static/main.mjs")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "import {installPollRegistry} from './modules/poll-registry.js?v=422511';",
    "import {installPollRegistry} from './modules/poll-registry.js?v=422517';",
    "main poll registry cache",
)
text = replace_once(
    text,
    "import {applyCleanConfirmation} from './modules/cleaning.js?v=421800';",
    "import {applyCleanConfirmation, cleanTaskView, isActiveCleanTask} from './modules/cleaning.js?v=422517';",
    "main cleaning import",
)
text = replace_once(
    text,
    "  cleaning: {applyCleanConfirmation},",
    "  cleaning: {applyCleanConfirmation, cleanTaskView, isActiveCleanTask},",
    "main cleaning platform core",
)
path.write_text(text, encoding="utf-8")


# 4) Current v427 clean tab consumes the view model and no longer owns setTimeout.
path = Path("static/app.js")
text = path.read_text(encoding="utf-8")
pattern = re.compile(
    r"  // ----- combined operation center -----\n"
    r"  async function loadOps427\(\).*?"
    r"\n\n  // ----- model config: prompt lives with model -----",
    re.S,
)
replacement = r'''  // ----- combined operation center -----
  async function loadOps427(){const [pl,cl]=await Promise.all([safe(api(`/api/v33/projects/${pid()}/prelabel-tasks`)),safe(api(`/api/v47/projects/${pid()}/clean-tasks`))]);state.prelabel427=pl?.items||[];state.clean427=cl?.items||[]}
  function opProgress427(t){return`<div class="opprog427"><i style="width:${t.progress||0}%"></i></div><span>${t.processed_images||0}/${t.total_images||0}</span>`}
  function cleanTaskView427(t){return window.PlatformCore?.cleaning?.cleanTaskView?.(t)||{...t,status:String(t.status||'').toLowerCase(),statusText:t.status_text||status427(t.status),percent:Number(t.progress||0),processed:Number(t.processed_images||0),total:Number(t.total_images||0),flagged:Number(t.flagged_images||0),progressText:`${Number(t.processed_images||0)}/${Number(t.total_images||0)}`,runtimeText:'',active:['queued','running'].includes(String(t.status||'').toLowerCase())}}
  function cleanStatus427(view){const s=view.status,c=s==='done'?'ok':s==='failed'?'err':s==='awaiting_confirmation'?'blue':'warn';return`<span class="pill ${c}">${esc(view.statusText)}</span>${view.runtimeText?`<div class="muted-line">${esc(view.runtimeText)}</div>`:''}`}
  function cleanProgress427(view){return`<div class="opprog427"><i style="width:${view.percent}%"></i></div><span>${esc(view.progressText)} · ${Number(view.percent||0).toFixed(1)}%</span>`}
  function cleanTaskRow427(t){const view=cleanTaskView427(t);return`<tr data-task-id="${esc(t.id)}"><td><b>${esc(t.name||t.id)}</b><div class="muted-line">OpenCV / 感知哈希</div></td><td>${cleanStatus427(view)}</td><td>${cleanProgress427(view)}</td><td>${view.flagged}</td><td>${fileTime427(t.created_at)}<div class="muted-line">${fileTime427(t.finished_at||t.finished_scan_at)}</div></td><td><div class="row"><button class="btn mini" onclick="showTaskProgress427('clean','${t.id}')">详情</button>${t.status==='awaiting_confirmation'?`<button class="btn mini primary" onclick="reviewClean427('${t.id}')">确认结果</button>`:''}</div></td></tr>`}
  function cleanTaskRows427(tasks){return(tasks||[]).map(cleanTaskRow427).join('')||'<tr><td colspan="6">暂无任务</td></tr>'}
  window.refreshCleanOps427Delta=async function(){
    if(state.page!=='自动标注及清洗'||(state.v427OpsTab||'label')!=='clean'){window.PollRegistryRuntime?.replaceCleanTaskTimer?.();return}
    const cl=await safe(api(`/api/v47/projects/${pid()}/clean-tasks`));
    if(cl)state.clean427=cl.items||[];
    if(state.page==='自动标注及清洗'&&(state.v427OpsTab||'label')==='clean'){
      const body=document.getElementById('clean427TaskRows');if(body)body.innerHTML=cleanTaskRows427(state.clean427||[])
    }
    window.PollRegistryRuntime?.replaceCleanTaskTimer?.()
  };
  window.renderOps427=async function(){await loadOps427();const tab=state.v427OpsTab;const rows=tab==='clean'?cleanTaskRows427(state.clean427):(state.prelabel427||[]).map(t=>`<tr><td><b>${esc(t.name||t.id)}</b><div class="muted-line">${esc((t.requested_labels||[t.target_label]).filter(Boolean).join('、'))}</div></td><td>${pill427(t.status)}</td><td>${opProgress427(t)}</td><td>${t.boxes_added||0}</td><td>${fileTime427(t.created_at)}<div class="muted-line">${fileTime427(t.finished_at||t.finished_scan_at)}</div></td><td><div class="row"><button class="btn mini" onclick="showTaskProgress427('label','${t.id}')">详情</button>${t.status==='awaiting_confirmation'?`<button class="btn mini primary" onclick="reviewAiLabel427('${t.id}')">确认结果</button>`:''}</div></td></tr>`).join('')||'<tr><td colspan="6">暂无任务</td></tr>';document.getElementById('view').innerHTML=`<section class="ops427"><div class="ops427-head"><div class="seg"><button class="${tab==='label'?'on':''}" onclick="state.v427OpsTab='label';renderOps427()">AI自动标注</button><button class="${tab==='clean'?'on':''}" onclick="state.v427OpsTab='clean';renderOps427()">自动清洗</button></div><button class="btn primary" onclick="${tab==='label'?'createAiLabel427()':'createClean427()'}">＋ 创建${tab==='label'?'AI标注':'清洗'}任务</button></div><section class="panel"><div class="table-wrap"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>${tab==='clean'?'真实处理进度':'处理进度'}</th><th>${tab==='label'?'候选框':'问题图片'}</th><th>时间</th><th>操作</th></tr></thead><tbody${tab==='clean'?' id="clean427TaskRows"':''}>${rows}</tbody></table></div></section></section>`;if(tab==='clean')window.PollRegistryRuntime?.replaceCleanTaskTimer?.()};

  // ----- model config: prompt lives with model -----'''
text, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise SystemExit(f"app clean operation-center patch: expected one match, got {count}")
# Switching back to v60 AI list must clear any clean one-shot immediately rather than waiting for expiry.
old = "    if((state.v427OpsTab||'label')==='clean'){window.AutoLabelPollRuntime?.deactivate?.();return previousRenderOps?.()}\n    try{"
new = "    if((state.v427OpsTab||'label')==='clean'){window.AutoLabelPollRuntime?.deactivate?.();return previousRenderOps?.()}\n    window.PollRegistryRuntime?.replaceCleanTaskTimer?.();\n    try{"
text = replace_once(text, old, new, "v60 clears clean poll on label tab")
if "setTimeout(()=>{if(state.page==='自动标注及清洗')renderOps427()},2200)" in text:
    raise SystemExit("legacy clean operation-center recursive timer still present")
path.write_text(text, encoding="utf-8")


# 5) Browser cache bust only; visible VERSION remains untouched.
path = Path("static/index.html")
text = path.read_text(encoding="utf-8")
text = replace_once(text, "/static/app.js?v=42.25.95", "/static/app.js?v=42.25.96", "app cache query")
text = replace_once(text, "/static/main.mjs?v=42.25.92", "/static/main.mjs?v=42.25.93", "main cache query")
path.write_text(text, encoding="utf-8")

print("cleaning frontend queue/progress truth migration applied")
