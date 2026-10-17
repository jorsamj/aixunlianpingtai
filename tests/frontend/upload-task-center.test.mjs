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
  recoverUploadTaskAfterRefresh,
  renderUploadTaskCenterRow,
  retainUploadTaskRows,
  stableUploadTaskOrder,
  summarizeUploadTasks,
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
  for (const status of ['WAITING_UPLOAD','MAPPING_LABELS','WRITING_ANNOTATIONS','INDEXING']) {
    assert.equal(isUploadTaskActive({status}), true, status);
  }
});

test('task center distinguishes browser transfer slots from visible FIFO waiters', () => {
  const tasks = [
    {id:'zip:a',status:'UPLOADING',browserTransfer:true},
    {id:'zip:b',status:'UPLOADING',browserTransfer:true},
    {id:'zip:c',status:'WAITING_UPLOAD'},
    {id:'zip:d',status:'WAITING_UPLOAD'},
    {id:'zip:e',status:'WAITING_UPLOAD'},
  ];
  assert.deepEqual(summarizeUploadTasks(tasks), {
    total:5,
    active:5,
    uploading:2,
    queued:3,
    terminal:0,
  });
});

test('all active uploads survive history bounds and terminal history stays bounded', () => {
  const active = Array.from({length:27}, (_,index) => ({
    id:`active-${index}`, status:'WAITING_UPLOAD', createdAt:`2026-10-13T00:${String(index).padStart(2,'0')}:00Z`,
  }));
  const terminal = Array.from({length:12}, (_,index) => ({
    id:`done-${index}`, status:'DONE', createdAt:`2026-10-12T00:${String(index).padStart(2,'0')}:00Z`,
  }));
  const retained = retainUploadTaskRows([...terminal,...active], 30);
  assert.equal(retained.filter(isUploadTaskActive).length, 27);
  assert.equal(retained.length, 30);
});

test('browser-only queued ZIP explicitly requires re-selection after refresh', () => {
  const recovered = recoverUploadTaskAfterRefresh({
    id:'zip:local-1',kind:'zip',title:'queued.zip',status:'WAITING_UPLOAD',
    localOnly:true,browserTransfer:false,progress:0,
  });
  assert.equal(recovered.status,'INTERRUPTED');
  assert.equal(recovered.resumeRequired,false);
  assert.match(recovered.stage,/重新选择/);
  assert.match(recovered.detail,/浏览器文件/);
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
  assert.match(main, /Promise\.resolve\(canonicalStartupPromise\)\.then\(\(\) => \{[\s\S]*?uploadTaskCenterRuntime\.switchProject\?\.\(\)/);
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
  assert.match(runtime, /build:'upload-task-center-4'/);
});


test('task center durable polling is PollRegistry-owned and hidden tabs do not keep requesting', () => {
  const runtime = readFileSync(new URL('../../static/modules/upload-task-center.js', import.meta.url), 'utf8');
  const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
  assert.match(runtime, /registry\?\.startTimeout\(POLL_KEY, pollOwners/);
  assert.match(runtime, /document\.visibilityState === 'hidden'/);
  assert.match(runtime, /visibilitychange/);
  assert.doesNotMatch(runtime, /setTimeout\(/);
  assert.doesNotMatch(runtime, /clearTimeout\(/);
  assert.match(main, /pollRegistry,[\s\S]*ownerPages: window\.PlatformCore\?\.navigation\?\.knownPages/);
});


test('ZIP task center rows reopen their durable runtime instead of becoming dead history',()=>{
  const html=renderUploadTaskCenterRow({
    id:'zip:job-1',kind:'zip',title:'fire.zip',status:'SELECTING',progress:38,stage:'等待确认标注',
  });
  assert.match(html,/data-utc-kind="zip"/);
  assert.match(html,/utc-reopenable/);
  assert.match(html,/tabindex="0"/);
  const runtime=readFileSync(new URL('../../static/modules/upload-task-center.js',import.meta.url),'utf8');
  assert.match(runtime,/ZipImportRuntime\?\.openTask\?\./);
  assert.match(runtime,/\.utc-row\[data-utc-kind="zip"\]/);
});

test('queued ZIP row shows size, FIFO position and local cancel without pretending to be reopenable',()=>{
  const html=renderUploadTaskCenterRow({
    id:'zip:local-3',kind:'zip',title:'third.zip',status:'WAITING_UPLOAD',progress:0,
    stage:'等待上传',fileSize:1536,queuePosition:1,localOnly:true,
  });
  assert.match(html,/1\.5 KB/);
  assert.match(html,/排队第 1 位/);
  assert.match(html,/data-utc-action="cancel-local"/);
  assert.doesNotMatch(html,/utc-reopenable/);
});


test('paused ZIP task remains visible and can be resumed after page refresh', () => {
  assert.equal(isUploadTaskActive({id:'zip:paused',kind:'zip',status:'PAUSED'}),true);
  const html=renderUploadTaskCenterRow({
    id:'zip:paused',kind:'zip',title:'dataset.zip',status:'PAUSED',stage:'上传已暂停',progress:48,
  });
  assert.match(html,/已暂停/);
  assert.match(html,/utc-reopenable/);
});

test('concurrent uploads keep identity order across changing server timestamps', () => {
  const first = mergeUploadTask({}, {id:'zip:first',createdAt:'2026-10-12T09:00:00Z',updatedAt:'2026-10-12T09:20:00Z'});
  const second = mergeUploadTask({}, {id:'zip:second',createdAt:'2026-10-12T09:01:00Z',updatedAt:'2026-10-12T09:02:00Z'});
  assert.deepEqual(stableUploadTaskOrder([first,second]).map(row=>row.id), ['zip:second','zip:first']);
  const changed = mergeUploadTask(first, {progress:75,updatedAt:'2026-10-12T09:30:00Z'});
  assert.deepEqual(stableUploadTaskOrder([changed,second]).map(row=>row.id), ['zip:second','zip:first']);
});

test('task dock stays clickable over upload modal and supports stable ID rekeying', () => {
  const source = readFileSync(new URL('../../static/modules/upload-task-center.js', import.meta.url), 'utf8');
  assert.match(source, /utc-root\{position:fixed;right:20px;bottom:18px;z-index:1300/);
  assert.match(source, /function rekey\(oldId, newId\)/);
  assert.match(source, /rows = stableUploadTaskOrder\(rows\)/);
  assert.doesNotMatch(source, /rows\.sort\(\(a,b\) => String\(b\.updatedAt\)/);
  assert.doesNotMatch(source, /rows\.slice\(0,\s*10\)/);
});
