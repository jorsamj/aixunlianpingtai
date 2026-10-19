import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {installMaterialBatchRuntime} from '../../static/modules/material-batches.js';

const source = readFileSync(new URL('../../static/modules/material-batches.js', import.meta.url), 'utf8');
const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

test('ordinary DELETE_INDEX completion invalidates the old integrity audit, not only dedup plans', async () => {
  const previous={window:globalThis.window,localStorage:globalThis.localStorage,fetch:globalThis.fetch};
  const calls=[];
  globalThis.localStorage={getItem:()=>null,setItem:()=>{}};
  globalThis.window={invalidateMaterialIntegrityGovernance47:async task=>{calls.push(task.task_id)}};
  globalThis.fetch=async()=>new Response(JSON.stringify({task_id:'ordinary-delete',operation:'DELETE_INDEX',status:'SUCCEEDED',total:2,processed:2,succeeded:2}));
  try{
    installMaterialBatchRuntime({projectId:()=> 'p1',notify:()=>{},refresh:async()=>calls.push('refresh'),pollRegistry:{clear:()=>{},startTimeout:()=>{}}});
    window.MaterialBatchRuntime62.poll('ordinary-delete');
    await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(calls,['refresh','ordinary-delete']);
  }finally{Object.assign(globalThis,previous)}
});

test('a delayed material task response cannot mutate the next project or keep polling it', async () => {
  const previous={window:globalThis.window,localStorage:globalThis.localStorage,fetch:globalThis.fetch};
  let project='p1',respond,mutations=0,url;
  globalThis.localStorage={getItem:()=>null,setItem:()=>{mutations++}};
  globalThis.window={updateMaterialIntegrityTask47:()=>{mutations++}};
  globalThis.fetch=async input=>{url=input;return new Promise(resolve=>{respond=resolve})};
  try{
    installMaterialBatchRuntime({projectId:()=>project,notify:()=>{mutations++},refresh:async()=>{mutations++},pollRegistry:{clear:()=>{},startTimeout:()=>{mutations++}}});
    window.MaterialBatchRuntime62.poll('task-a');project='p2';
    respond(new Response(JSON.stringify({task_id:'task-a',operation:'DELETE_INDEX',status:'SUCCEEDED'})));
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(url,'/api/v62/projects/p1/material-batches/task-a');
    assert.equal(mutations,0);
  }finally{Object.assign(globalThis,previous)}
});

test('a project switch during terminal refresh cannot expire the next project audit', async () => {
  const previous={window:globalThis.window,localStorage:globalThis.localStorage,fetch:globalThis.fetch};
  let project='A',release,entered,invalidations=0;
  const gate=new Promise(resolve=>{release=resolve}),refreshEntered=new Promise(resolve=>{entered=resolve});
  globalThis.localStorage={getItem:()=>null,setItem:()=>{}};
  globalThis.window={invalidateMaterialIntegrityGovernance47:async()=>{invalidations++}};
  globalThis.fetch=async()=>new Response(JSON.stringify({task_id:'A-delete',project_id:'A',operation:'DELETE_INDEX',status:'SUCCEEDED'}));
  try{
    installMaterialBatchRuntime({projectId:()=>project,notify:()=>{},refresh:async()=>{entered();await gate},pollRegistry:{clear:()=>{},startTimeout:()=>{}}});
    window.MaterialBatchRuntime62.poll('A-delete');await refreshEntered;
    project='B';release();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(invalidations,0,'old project completion must not touch the new audit');
  }finally{Object.assign(globalThis,previous)}
});

test('material batch polling is centrally owned and resumes only on relevant pages', () => {
  assert.match(source, /pollRegistry \|\| window\.PollRegistryRuntime/);
  assert.match(source, /registry\.startTimeout\(pollKey\(id\), POLL_OWNERS, tick, 1500\)/);
  assert.match(source, /const POLL_OWNERS = \['数据集', '自动标注及清洗', '训练任务', '算法列表'\]/);
  assert.match(source, /build: 'material-batch-runtime-422408'/);
  assert.doesNotMatch(source, /setTimeout\(/);
  assert.doesNotMatch(source, /clearTimeout\(/);
  assert.doesNotMatch(source, /const timers = new Map/);
  assert.match(main, /window\.MaterialBatchRuntime62\?\.resume\?\.\(\)/);
});


test('large explicit ready selections reuse the durable material-batch owner', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /imageIds = \[\], skipConfirm = false/);
  assert.match(source, /selection\(chosen, imageIds\)/);
  assert.match(source, /explicitIds\?\.length \? explicitIds/);
  assert.match(source, /!skipConfirm && !window\.confirm/);
  const start = app.indexOf('window.confirmBatch414=function(mode)');
  const end = app.indexOf('// ---------- stable algorithm CRUD ----------', start);
  assert.ok(start >= 0 && end > start);
  const owner = app.slice(start, end);
  assert.match(owner, /runMaterialBatch62\('MARK_CLEAN_SKIPPED',\{scope:'SELECTED',imageIds:ids,skipConfirm:true\}\)/);
  assert.match(owner, /if\(mode==='clean'\)return createClean427\(\{image_ids:ids\}\)/);
});


test('material batch terminal truth refreshes the canonical dataset page owner', () => {
  const pollStart = source.indexOf('function poll(taskId,');
  const resumeStart = source.indexOf('function resume()', pollStart);
  assert.ok(pollStart >= 0 && resumeStart > pollStart);
  const pollOwner = source.slice(pollStart, resumeStart);
  assert.match(pollOwner, /if \(isMaterialBatchActive\(task\)\)/);
  assert.match(pollOwner, /else \{[\s\S]*stopPolling\(id\);[\s\S]*await refresh\?\.\(\)/);
  assert.match(main, /refresh: async \(\) => \{[\s\S]*await window\.reloadMaterialPage61\?\.\(\)/);
  assert.match(pollOwner, /task\.operation === 'DELETE_INDEX'/);
  assert.match(pollOwner, /invalidateMaterialIntegrityGovernance47/);
  assert.match(source, /完成组 \$\{Number\(task\.completed_groups \|\| 0\)\}/);
  assert.match(source, /失败组 \$\{Number\(task\.failed_groups \|\| 0\)\}/);
});


test('restoring finished clean/skip task does not open AI review modal',()=>{
  const source=readFileSync(new URL('../../static/modules/material-batches.js',import.meta.url),'utf8');
  assert.match(source,/foreground && task\.operation === 'AI_ANNOTATE' && task\.review_required/);
  assert.match(source,/poll\(taskId\);/);
  assert.match(source,/poll\(task\.task_id, \{foreground: true\}\)/);
});

test('filtered material deletion estimates and freezes server-owned scope with annotation cleanup', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const pagination = readFileSync(new URL('../../static/modules/material-pagination-runtime.js', import.meta.url), 'utf8');
  assert.match(app, /删除筛选结果/);
  assert.match(pagination, /window.deleteFilteredMaterials61 = async/);
  assert.match(pagination, /scope: 'FILTERED'/);
  assert.match(pagination, /if \(!narrowed\)/);
  assert.match(source, /payload.selection_spec = estimate.selection_spec/);
  assert.match(source, /Ground Truth 与标注文件/);
});
