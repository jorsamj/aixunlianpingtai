from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


module_path = Path("static/modules/video-tasks.js")
module = module_path.read_text(encoding="utf-8")
module = replace_once(
    module,
    "const ACTIVE = new Set(['QUEUED', 'RUNNING', 'CANCEL_REQUESTED']);",
    "const ACTIVE = new Set(['QUEUED', 'WAITING_RESOURCE', 'RUNNING', 'CANCEL_REQUESTED']);",
    "video active public statuses",
)
module = replace_once(
    module,
    "  QUEUED: '排队中',\n  RUNNING: '处理中',",
    "  QUEUED: '排队中',\n  WAITING_RESOURCE: '等待资源',\n  RUNNING: '处理中',",
    "video waiting-resource status text",
)
module = replace_once(
    module,
    "  else if (task.mode === 'interval_seconds') samplingText = `每 ${Number(task.interval_seconds || 0)} 秒 1 帧`;\n  return {",
    "  else if (task.mode === 'interval_seconds') samplingText = `每 ${Number(task.interval_seconds || 0)} 秒 1 帧`;\n  const queuePosition = Math.max(0, Number(task.resource_queue_position) || 0);\n  const waitReason = String(task.resource_wait_reason || '').trim();\n  const queuedRuntime = queuePosition\n    ? `资源队列第 ${queuePosition} 位${waitReason ? ` · ${waitReason}` : ''}`\n    : (waitReason ? `等待资源 · ${waitReason}` : '');\n  const runtimeText = ['QUEUED', 'WAITING_RESOURCE'].includes(status) ? queuedRuntime : '';\n  return {",
    "video queue runtime projection",
)
module = replace_once(
    module,
    "    statusText: STATUS_TEXT[status] || status,\n    samplingText,",
    "    statusText: STATUS_TEXT[status] || status,\n    queuePosition,\n    waitReason,\n    runtimeText,\n    samplingText,",
    "video queue view fields",
)
module_path.write_text(module, encoding="utf-8")

app_path = Path("static/app.js")
app = app_path.read_text(encoding="utf-8")
app = replace_once(
    app,
    "</td><td>${splitName424(t.split||'unassigned')}</td><td>${taskStatus424(t)}</td><td><div class=\"progress424\">",
    "</td><td>${splitName424(t.split||'unassigned')}</td><td>${taskStatus424(t)}${t.runtimeText?`<div class=\"muted-line\">${esc(t.runtimeText)}</div>`:''}</td><td><div class=\"progress424\">",
    "final v424 video queue metadata renderer",
)
app_path.write_text(app, encoding="utf-8")
