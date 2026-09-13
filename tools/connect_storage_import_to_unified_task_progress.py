from pathlib import Path

POLLER = Path('static/modules/task-poller.js')
STORAGE = Path('static/modules/storage-import-progress.js')
MAIN = Path('static/main.mjs')
INDEX = Path('static/index.html')
POLLER_TEST = Path('tests/frontend/task-poller.test.mjs')
STORAGE_TEST = Path('tests/frontend/storage-import-progress.test.mjs')

poller = POLLER.read_text(encoding='utf-8')
poller = poller.replace(
    "const ACTIVE = new Set(['QUEUED', 'RUNNING', 'CANCEL_REQUESTED']);",
    "const ACTIVE = new Set(['QUEUED', 'WAITING_RESOURCE', 'PREPARING', 'RUNNING', 'PAUSING', 'PAUSED', 'RESUMING', 'CANCEL_REQUESTED', 'RETRYING']);",
    1,
)
old_progress = '''export function taskProgress(task = {}) {\n  const clamp = value => Math.max(0, Math.min(100, Number(value) || 0));\n  return {\n    percent: clamp(task.progress),\n    completed: Math.max(0, Number(task.completed_count) || 0),\n    total: Math.max(0, Number(task.total_count) || 0),\n    failed: Math.max(0, Number(task.failed_count) || 0)\n  };\n}\n'''
new_progress = '''export function taskProgress(task = {}) {\n  const clamp = value => Math.max(0, Math.min(100, Number(value) || 0));\n  return {\n    percent: clamp(task.progress_percent ?? task.progress),\n    completed: Math.max(0, Number(task.completed_units ?? task.completed_count) || 0),\n    total: Math.max(0, Number(task.total_units ?? task.total_count) || 0),\n    failed: Math.max(0, Number(task.failed_units ?? task.failed_count) || 0)\n  };\n}\n'''
if poller.count(old_progress) != 1:
    raise SystemExit('taskProgress anchor missing')
poller = poller.replace(old_progress, new_progress, 1)
POLLER.write_text(poller, encoding='utf-8')

storage = STORAGE.read_text(encoding='utf-8')
if not storage.startswith('export function storageImportProgressText'):
    raise SystemExit('unexpected storage progress module header')
storage = "import {isTaskActive, taskProgress} from './task-poller.js?v=422001';\n\n" + storage
old_text = '''export function storageImportProgressText(task = {}) {\n  const stage = String(task.stage || task.status || 'SCANNING');\n  const current = String(task.current_item || '').trim();\n  if (current) return `${stage} · ${current}`;\n  if (stage === 'QUEUED') return '已进入扫描队列';\n  if (stage === 'FINALIZING') return '正在整理扫描结果';\n  return `${stage} · 正在扫描对象`;\n}\n'''
new_text = '''export function storageImportProgressText(task = {}) {\n  const status = String(task.status || '').toUpperCase();\n  const stage = String(task.phase || task.stage || status || 'SCANNING');\n  const current = String(task.current_item || '').trim();\n  const {percent} = taskProgress(task);\n  const queuePosition = Number(task.resource_queue_position || 0);\n  const priority = Number(task.priority || 0);\n  const worker = String(task.worker_id || '').trim();\n  const waitReason = String(task.resource_wait_reason || '').trim();\n  if (status === 'WAITING_RESOURCE') {\n    return ['等待资源', queuePosition > 0 ? `队列第 ${queuePosition} 位` : '', waitReason].filter(Boolean).join(' · ');\n  }\n  if (status === 'QUEUED') {\n    return ['排队中', queuePosition > 0 ? `队列第 ${queuePosition} 位` : '', priority > 0 ? `优先级 ${priority}` : ''].filter(Boolean).join(' · ');\n  }\n  if (stage === 'FINALIZING') return percent > 0 ? `正在整理扫描结果 · ${percent.toFixed(0)}%` : '正在整理扫描结果';\n  const parts = [stage];\n  if (percent > 0) parts.push(`${percent.toFixed(0)}%`);\n  if (current) parts.push(current);\n  if (worker) parts.push(`执行节点 ${worker}`);\n  if (parts.length === 1) parts.push('正在扫描对象');\n  return parts.join(' · ');\n}\n'''
if storage.count(old_text) != 1:
    raise SystemExit('storage progress text anchor missing')
storage = storage.replace(old_text, new_text, 1)
old_loop = '''      let current = task;\n      while (['QUEUED', 'RUNNING'].includes(String(current.status || '').toUpperCase())) {\n        await new Promise(resolve => setTimeout(resolve, 1200));\n        // Closing the dialog only stops browser polling; the durable worker task keeps running.\n        if (status && !status.isConnected) return;\n        current = await responseJson(await fetch(\n          `/api/v61/projects/${encodeURIComponent(projectId)}/storage-imports/${encodeURIComponent(task.task_id)}`,\n        ));\n        if (status) status.textContent = storageImportProgressText(current);\n      }\n\n      if (String(current.status || '').toUpperCase() !== 'SUCCEEDED') {\n        throw new Error(current.error || `扫描未成功：${current.status || 'UNKNOWN'}`);\n      }\n      const result = current.result || {};\n'''
new_loop = '''      let current = task;\n      while (isTaskActive(current.status)) {\n        await new Promise(resolve => setTimeout(resolve, 1200));\n        // Closing the dialog only stops browser polling; the durable worker task keeps running.\n        if (status && !status.isConnected) return;\n        current = await responseJson(await fetch(\n          `/api/v62/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(task.task_id)}`,\n        ));\n        if (status) status.textContent = storageImportProgressText(current);\n      }\n\n      if (String(current.status || '').toUpperCase() !== 'SUCCEEDED') {\n        throw new Error(current.error || `扫描未成功：${current.status || 'UNKNOWN'}`);\n      }\n      const completed = await responseJson(await fetch(\n        `/api/v61/projects/${encodeURIComponent(projectId)}/storage-imports/${encodeURIComponent(task.task_id)}`,\n      ));\n      const result = completed.result || {};\n'''
if storage.count(old_loop) != 1:
    raise SystemExit('storage polling loop anchor missing')
storage = storage.replace(old_loop, new_loop, 1)
STORAGE.write_text(storage, encoding='utf-8')

main = MAIN.read_text(encoding='utf-8')
if "./modules/task-poller.js?v=422000" not in main or "./modules/storage-import-progress.js?v=422400" not in main:
    raise SystemExit('main module cache anchors missing')
main = main.replace("./modules/task-poller.js?v=422000", "./modules/task-poller.js?v=422001", 1)
main = main.replace("./modules/storage-import-progress.js?v=422400", "./modules/storage-import-progress.js?v=422401", 1)
MAIN.write_text(main, encoding='utf-8')

index = INDEX.read_text(encoding='utf-8')
if '/static/main.mjs?v=42.25.89' not in index:
    raise SystemExit('main cache anchor missing')
INDEX.write_text(index.replace('/static/main.mjs?v=42.25.89', '/static/main.mjs?v=42.25.90', 1), encoding='utf-8')

poller_test = POLLER_TEST.read_text(encoding='utf-8')
poller_test = poller_test.replace("  assert.equal(isTaskActive('QUEUED'), true);\n", "  assert.equal(isTaskActive('QUEUED'), true);\n  assert.equal(isTaskActive('WAITING_RESOURCE'), true);\n  assert.equal(isTaskActive('RETRYING'), true);\n", 1)
poller_test = poller_test.replace(
    "  assert.equal(taskProgress({progress: 180}).percent, 100);\n",
    "  assert.equal(taskProgress({progress: 180}).percent, 100);\n  assert.deepEqual(taskProgress({progress_percent: 42, completed_units: 21, total_units: 50, failed_units: 2}), {percent: 42, completed: 21, total: 50, failed: 2});\n",
    1,
)
POLLER_TEST.write_text(poller_test, encoding='utf-8')

STORAGE_TEST.write_text('''import test from 'node:test';\nimport assert from 'node:assert/strict';\nimport fs from 'node:fs';\n\nimport {storageImportProgressText} from '../../static/modules/storage-import-progress.js';\n\n\ntest('storage scan renders authoritative unified runtime progress', () => {\n  const text = storageImportProgressText({\n    status: 'RUNNING',\n    phase: 'SCANNING',\n    progress_percent: 37.5,\n    current_item: '已扫描 12531 / 可导入 9824 / 重复 2694 / 失败 13 / camera.jpg',\n    worker_id: 'storage-worker-01',\n  });\n  assert.equal(text, 'SCANNING · 38% · 已扫描 12531 / 可导入 9824 / 重复 2694 / 失败 13 / camera.jpg · 执行节点 storage-worker-01');\n});\n\n\ntest('queued and resource-waiting scans expose real queue state', () => {\n  assert.equal(storageImportProgressText({status: 'QUEUED', resource_queue_position: 3, priority: 1}), '排队中 · 队列第 3 位 · 优先级 1');\n  assert.equal(storageImportProgressText({status: 'WAITING_RESOURCE', resource_queue_position: 2, resource_wait_reason: 'RESOURCE_BUSY'}), '等待资源 · 队列第 2 位 · RESOURCE_BUSY');\n  assert.equal(storageImportProgressText({status: 'RUNNING', phase: 'FINALIZING', progress_percent: 91}), '正在整理扫描结果 · 91%');\n});\n\n\ntest('storage scan polls unified durable task truth while work is active', () => {\n  const source = fs.readFileSync('static/modules/storage-import-progress.js', 'utf8');\n  assert.match(source, /\\/api\\/v62\\/projects\\/\\$\\{encodeURIComponent\\(projectId\\)\\}\\/tasks\\/\\$\\{encodeURIComponent\\(task\\.task_id\\)\\}/);\n  assert.match(source, /while \\(isTaskActive\\(current\\.status\\)\\)/);\n  assert.match(source, /const completed=await responseJson|const completed = await responseJson/);\n});\n''', encoding='utf-8')

print('storage import unified task progress patch prepared')
