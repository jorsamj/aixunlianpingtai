import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  clearCompletedUploadTasks,
  hasTerminalZipUploadTasks,
  isUploadTaskActive,
  mergeUploadTask,
  normalizeDurableUploadTask,
  patchUploadTaskCenterRows,
  renderUploadTaskCenterRow,
} from '../../static/modules/upload-task-center.js';

test('mergeUploadTask keeps truthful progress and terminal success becomes 100%', () => {
  const active = mergeUploadTask({}, {id:'u1', status:'UPLOADING', progress:37.5, stage:'文件上传'});
  assert.equal(active.progress, 37.5);
  assert.equal(isUploadTaskActive(active), true);
  const done = mergeUploadTask(active, {status:'SUCCEEDED', stage:'完成'});
  assert.equal(done.progress, 100);
  assert.equal(isUploadTaskActive(done), false);
});

test('task center treats label mapping/indexing stages as active', () => {
  for (const status of ['MAPPING_LABELS','WRITING_ANNOTATIONS','INDEXING']) {
    assert.equal(isUploadTaskActive({status}), true, status);
  }
});

test('refresh keeps an interrupted browser ZIP session waiting instead of pretending bytes are still moving', () => {
  const row = mergeUploadTask({}, {
    id:'zip:u1', kind:'zip', status:'WAITING', progress:17.5,
    stage:'上传已暂停，等待继续', resumeRequired:true, browserTransfer:false,
  });
  const next = normalizeDurableUploadTask({
    status:'uploading', progress:17.5, updated_at:'2026-09-17T10:00:00Z',
    stage:'正在上传 ZIP', message:'server still has resumable parts',
  }, row);

  assert.equal(next.status, 'WAITING');
  assert.equal(next.progress, 17.5);
  assert.equal(next.resumeRequired, true);
  assert.match(next.stage, /等待继续/);
});

test('durable task can leave resume wait once backend advances beyond upload phase', () => {
  const row = mergeUploadTask({}, {
    id:'zip:u1', kind:'zip', status:'WAITING', progress:17.5,
    resumeRequired:true,
  });
  const next = normalizeDurableUploadTask({status:'selecting', progress:38, stage:'等待启动后台导入'}, row);

  assert.equal(next.status, 'SELECTING');
  assert.equal(next.progress, 38);
});


test('clear ended import history removes every terminal state but preserves active tasks', () => {
  const rows = [
    {id:'running', status:'RUNNING'},
    {id:'done', status:'SUCCEEDED'},
    {id:'failed', status:'FAILED'},
    {id:'cancelled', status:'CANCELLED'},
    {id:'interrupted', status:'INTERRUPTED'},
    {id:'waiting', status:'WAITING_RESOURCE'},
  ];
  assert.deepEqual(
    clearCompletedUploadTasks(rows).map(row => row.id),
    ['running', 'waiting'],
  );
});

test('terminal ZIP history requires durable backend cleanup before local removal', () => {
  assert.equal(hasTerminalZipUploadTasks([
    {id:'zip:done', kind:'zip', status:'DONE'},
    {id:'storage:done', kind:'storage-import', status:'SUCCEEDED'},
  ]), true);
  assert.equal(hasTerminalZipUploadTasks([
    {id:'zip:running', kind:'zip', status:'RUNNING'},
    {id:'storage:done', kind:'storage-import', status:'SUCCEEDED'},
  ]), false);
});



test('task center labels terminal cleanup as clear ended, not clear completed', () => {
  const runtime = readFileSync(new URL('../../static/modules/upload-task-center.js', import.meta.url), 'utf8');
  assert.match(runtime, />清空已结束<\/button>/);
  assert.doesNotMatch(runtime, />清空已完成<\/button>/);
  assert.match(runtime, /已清空 \$\{cleared\} 条已结束任务/);
  assert.doesNotMatch(runtime, /已清空 \$\{cleared\} 条已完成任务/);
});

test('task center yields durable polling while a focused runtime owns the task', () => {
  const runtime = readFileSync(new URL('../../static/modules/upload-task-center.js', import.meta.url), 'utf8');
  assert.match(runtime, /row\.serverUrl && !row\.pollOwner/);
  assert.match(runtime, /delete value\.pollOwner/);
  assert.match(runtime, /row\?\.pollOwner/);
});

test('project switching is navigation-owned and has no permanent interval', () => {
  const runtime = readFileSync(new URL('../../static/modules/upload-task-center.js', import.meta.url), 'utf8');
  const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
  assert.doesNotMatch(runtime, /setInterval\(switchProject,\s*1500\)/);
  assert.doesNotMatch(runtime, /__uploadTaskCenterProjectTimer/);
  assert.match(main, /uploadTaskCenterRuntime\.switchProject\?\.\(\)/);
});


test('task center row uses transform progress and patch fallback preserves canonical content', () => {
  const row = mergeUploadTask({}, {
    id:'upload-perf-1', title:'素材上传', status:'UPLOADING', progress:42.5,
    stage:'服务器处理中', detail:'425 / 1000',
    updatedAt:'2026-09-22T00:00:00Z',
  });
  const html = renderUploadTaskCenterRow(row);
  assert.match(html, /data-utc-id="upload-perf-1"/);
  assert.match(html, /scaleX\(0\.4250\)/);
  assert.doesNotMatch(html, /style="width:/);

  const body = {innerHTML:''};
  assert.equal(patchUploadTaskCenterRows(body, [row]), true);
  assert.match(body.innerHTML, /素材上传/);
  assert.match(body.innerHTML, /42\.5%/);
});

test('task center source keeps a stable shell and keyed row patch owner', () => {
  const runtime = readFileSync(new URL('../../static/modules/upload-task-center.js', import.meta.url), 'utf8');
  assert.match(runtime, /function ensureShell\(root\)/);
  assert.match(runtime, /patchUploadTaskCenterRows\(body, visible\)/);
  assert.match(runtime, /data-progress=/);
  assert.match(runtime, /build:'upload-task-center-2'/);
});
