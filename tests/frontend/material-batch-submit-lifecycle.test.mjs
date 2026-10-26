import test from 'node:test';
import assert from 'node:assert/strict';
import {installMaterialBatchRuntime} from '../../static/modules/material-batches.js';
import {readFileSync} from 'node:fs';
import {withRequestDeadline} from '../../static/modules/api.js';

async function fixture(run,{refresh,projectId=()=> 'p1',pollRegistry={clear(){},startTimeout(){}}}={}) {
  const previous={window:globalThis.window,localStorage:globalThis.localStorage,fetch:globalThis.fetch};
  const storage=new Map(),calls=[],messages=[];
  globalThis.localStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)};
  globalThis.window={confirm:()=>true};
  try {
    installMaterialBatchRuntime({projectId,currentPageIds:()=>['one'],refresh,notify:value=>messages.push(value),requestTimeoutMs:15,pollRegistry});
    await run({calls,messages});
  } finally {Object.assign(globalThis,previous)}
}
test('smart audit uses the original poll key on labels and intake without expanding ordinary task owners',async()=>{
 const owners=[];
 await fixture(async()=>{
  const task={task_id:'smart-live',project_id:'p1',kind:'MATERIAL_BATCH',operation:'SMART_AUDIT',status:'RUNNING'};
  globalThis.fetch=async()=>Response.json(task);
  await window.MaterialBatchRuntime62.submitSmart({options:{request_id:'labels'}});
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(owners.some(row=>row.key==='material-batch:smart-live'&&row.pages.includes('标签管理')&&row.pages.includes('素材接入')));
 },{pollRegistry:{clear(){},startTimeout:(key,pages)=>owners.push({key,pages})}});
});
test('material cancellation is bounded and late old-project cancellation cannot announce into the next project',async()=>{
 let project='p1';
 await fixture(async()=>{
  globalThis.fetch=async()=>new Promise(()=>{});
  const result=await Promise.race([window.cancelMaterialBatch62('pending').catch(error=>error.code),new Promise(resolve=>setTimeout(()=>resolve('unbounded'),80))]);
  assert.equal(result,'REQUEST_TIMEOUT');
  let release,announced=0;window.SmartMaterialAuditRuntime={onTask:()=>announced++};
  globalThis.fetch=async()=>new Promise(resolve=>release=()=>resolve(Response.json({task_id:'old',project_id:'p1',operation:'SMART_AUDIT',status:'CANCEL_REQUESTED'})));
  const cancel=window.cancelMaterialBatch62('old');await new Promise(resolve=>setImmediate(resolve));project='p2';release();await cancel;
  assert.equal(announced,0);assert.equal(localStorage.getItem('aixunlian.material-batches.v62'),null);
 },{projectId:()=>project});
});
test('smart analysis uncertainty retries the same request without blocking original CLEAN',()=>fixture(async()=>{
  const requests=[];let cleanPosts=0;
  globalThis.fetch=async(url,options={})=>{
    if(url.endsWith('smart-material-audit')){requests.push(JSON.parse(options.body));throw new TypeError('lost response');}
    if(url.endsWith('/estimate'))return Response.json({supported:true,count:1,selection_spec:{scope:'CURRENT_PAGE',image_ids:['one']}});
    if(options.method==='POST')cleanPosts++;
    return Response.json({task_id:'clean',operation:'CLEAN',status:'SUCCEEDED'});
  };
  const body={selection_spec:{scope:'SELECTED',image_ids:['one']},options:{request_id:'original'}};
  await assert.rejects(window.MaterialBatchRuntime62.submitSmart(body),/lost/);
  assert.deepEqual(window.MaterialBatchRuntime62.pendingSmart().payload,body);
  await window.runMaterialBatch62('CLEAN',{scope:'CURRENT_PAGE'});
  assert.equal(cleanPosts,1);
  await assert.rejects(window.MaterialBatchRuntime62.submitSmart({...body,options:{request_id:'replacement'}}),/lost/);
  assert.equal(requests.length,2);assert.deepEqual(requests[0],requests[1]);
}));
test('smart analysis coalesces clicks, validates project identity and clears accepted pending',()=>fixture(async()=>{
  let release,posts=0;
  const task={task_id:'smart-1',project_id:'p1',kind:'MATERIAL_BATCH',operation:'SMART_AUDIT',status:'SUCCEEDED'};
  globalThis.fetch=async(url,options={})=>{if(options.method==='POST'){posts++;return new Promise(resolve=>release=()=>resolve(Response.json(task)));}return Response.json(task);};
  const first=window.MaterialBatchRuntime62.submitSmart({options:{request_id:'one'}}),second=window.MaterialBatchRuntime62.submitSmart({options:{request_id:'two'}});
  assert.equal(first,second);await new Promise(resolve=>setImmediate(resolve));release();await first;
  assert.equal(posts,1);assert.equal(window.MaterialBatchRuntime62.pendingSmart(),null);
}));
test('read-only smart completion never refreshes or clears the original material editing selection',async()=>{
  let refreshed=0;
  await fixture(async()=>{
    const task={task_id:'smart-readonly',project_id:'p1',kind:'MATERIAL_BATCH',operation:'SMART_AUDIT',status:'SUCCEEDED'};
    globalThis.fetch=async()=>Response.json(task);
    await window.MaterialBatchRuntime62.submitSmart({options:{request_id:'readonly'}});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(refreshed,0);
  },{refresh:async()=>refreshed++});
});
test('material estimate and create share one submission and release the original busy button',()=>fixture(async()=>{
  let release,posts=0;
  globalThis.fetch=async url=>{
    if(url.endsWith('/estimate'))return new Promise(resolve=>{release=()=>resolve(Response.json({supported:true,count:1,selection_spec:{scope:'CURRENT_PAGE',image_ids:['one']}}))});
    if(url.endsWith('material-batches')){posts++;return Response.json({task_id:'t1',operation:'CLEAN',status:'SUCCEEDED'})}
    return Response.json({task_id:'t1',operation:'CLEAN',status:'SUCCEEDED'});
  };
  const attrs=new Map(),button={disabled:false,isConnected:true,setAttribute:(k,v)=>attrs.set(k,v),removeAttribute:k=>attrs.delete(k)};
  const first=window.runMaterialBatch62('CLEAN',{scope:'CURRENT_PAGE',triggerButton:button});
  const second=window.runMaterialBatch62('CLEAN',{scope:'CURRENT_PAGE',triggerButton:button});
  assert.equal(button.disabled,true);assert.equal(attrs.get('aria-busy'),'true');
  await new Promise(resolve=>setImmediate(resolve));release();await Promise.all([first,second]);assert.equal(posts,1);assert.equal(button.disabled,false);assert.equal(attrs.has('aria-busy'),false);
}));
test('unknown material creation remains locked across clicks and refresh while querying existing tasks',()=>fixture(async({messages})=>{
  let posts=0,lists=0;
  globalThis.fetch=async url=>{
    if(url.endsWith('/estimate'))return Response.json({supported:true,count:1,selection_spec:{scope:'CURRENT_PAGE',image_ids:['one']}});
    if(url.includes('?')){lists++;return Response.json({items:[]})}
    posts++;throw new TypeError('connection lost after acceptance');
  };
  await window.runMaterialBatch62('CLEAN',{scope:'CURRENT_PAGE'});
  window.__materialBatchRuntime62Installed=false;
  installMaterialBatchRuntime({projectId:()=> 'p1',notify:value=>messages.push(value),requestTimeoutMs:15,pollRegistry:{clear(){},startTimeout(){}}});
  await window.runMaterialBatch62('CLEAN',{scope:'CURRENT_PAGE'});
  assert.equal(posts,1);assert.ok(lists>=1);assert.match(messages.join(' '),/结果待确认/);
}));
test('material estimate pending is bounded without posting a mutation',()=>fixture(async({messages})=>{
  globalThis.fetch=async()=>new Promise(()=>{});
  await window.runMaterialBatch62('CLEAN',{scope:'CURRENT_PAGE'});
  assert.match(messages.join(' '),/超时/);
}));

test('logical delete carries the frozen preview credential and shows actual retention before creation',()=>fixture(async()=>{
  let posted, confirmation='';
  window.confirm=text=>{confirmation=text;return true};
  globalThis.fetch=async(url,options={})=>{
    if(url.endsWith('/estimate'))return Response.json({supported:true,count:2,selection_spec:{scope:'SELECTED',image_ids:['one','two'],repository_revision:9},
      deletion_preview:{plan_id:'plan-safe',confirmation_credential:'proof',selected_count:2,gt_count:1,current_test_count:1,historical_reference_count:2,active_reference_count:1,physical_retained_count:2,reclaimed_bytes:0}});
    if(options.method==='POST'){posted=JSON.parse(options.body);return Response.json({task_id:'plan-safe',operation:'DELETE_INDEX',status:'QUEUED'})}
    return Response.json({task_id:'plan-safe',operation:'DELETE_INDEX',status:'QUEUED'});
  };
  await window.runMaterialBatch62('DELETE_INDEX',{scope:'SELECTED',imageIds:['one','two'],skipConfirm:true});
  assert.equal(posted.options.deletion_plan_id,'plan-safe');assert.equal(posted.options.confirmation_credential,'proof');
  assert.match(confirmation,/正式 GT 1/);assert.match(confirmation,/活动引用 1/);assert.match(confirmation,/释放空间 0/);
}));

test('project clear freezes an unfiltered project and rejects a wrong name without posting',()=>fixture(async({messages})=>{
  let requests=0;
  window.prompt=()=> 'wrong';
  globalThis.fetch=async()=>{requests++;throw Error('must not request')};
  await window.runMaterialBatch62('DELETE_INDEX',{scope:'PROJECT',options:{project_name:'Current Project'}});
  assert.equal(requests,0);assert.match(messages.join(' '),/项目名称/);
}));

test('a late delete submission carries the original training context instead of capturing a replacement draft',()=>fixture(async()=>{
  const original={taskId:'training-original'},replacement={taskId:'training-replacement'},tracked=[];
  let context=original,release;
  window.TrainingMaterialSummaryRuntime={captureDeletionContext:()=>context,trackMaterialDeletion:(_task,value)=>tracked.push(value)};
  globalThis.fetch=async(url,options={})=>{
    if(url.endsWith('/estimate'))return Response.json({supported:true,count:1,selection_spec:{scope:'SELECTED',image_ids:['one']}});
    if(options.method==='POST')return new Promise(resolve=>{release=()=>resolve(Response.json({task_id:'queued-delete',operation:'DELETE_INDEX',status:'QUEUED'}))});
    return Response.json({task_id:'queued-delete',operation:'DELETE_INDEX',status:'QUEUED'});
  };
  const pending=window.runMaterialBatch62('DELETE_INDEX',{scope:'SELECTED',imageIds:['one']});
  while(!release)await new Promise(resolve=>setImmediate(resolve));
  context=replacement;release();await pending;assert.deepEqual(tracked,[original]);
}));

test('delete terminal updates training from results even when dataset refresh fails',()=>fixture(async({messages})=>{
  const ids=[];
  window.TrainingMaterialSummaryRuntime={onMaterialBatchCompleted:async task=>ids.push(task.task_id)};
  globalThis.fetch=async()=>Response.json({task_id:'delete-a',project_id:'p1',operation:'DELETE_INDEX',status:'PARTIAL_SUCCESS'});
  window.MaterialBatchRuntime62.poll('delete-a');
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(ids,['delete-a']);
  assert.match(messages.join(' '),/列表刷新失败/);
},{refresh:async()=>{throw new Error('isolated list refresh failure')}}));
test('material polling pending stops with a recoverable timeout message',()=>fixture(async({messages})=>{
  globalThis.fetch=async()=>new Promise(()=>{});
  window.MaterialBatchRuntime62.poll('existing-task');
  await new Promise(resolve=>setTimeout(resolve,35));
  assert.match(messages.join(' '),/超时/);
}));
test('audit submission uncertainty queries latest instead of asserting no creation',()=>{
  const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
  const block=source.slice(source.indexOf('window.startMaterialIntegrityAudit47=async function(){'),source.indexOf('function materialIntegrityDuplicate47'));
  assert.doesNotMatch(block,/没有创建新的审计任务/);
  assert.match(block,/audits\/latest/);
  assert.match(block,/结果待确认/);
});

test('audit lost response queries latest and never treats the old audit as recovered',async()=>{
  const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
  const block=source.slice(source.indexOf('window.startMaterialIntegrityAudit47=async function(){'),source.indexOf('function materialIntegrityDuplicate47'));
  const storage=new Map(),state={},calls=[],box={},retry={},root={isConnected:true,dataset:{},querySelector:selector=>selector.includes('retry')?retry:box};
  let latest={task:{task_id:'old-audit'}},project='p1',postCount=0;
  const win={PlatformCore:{withRequestDeadline:(fn,options)=>withRequestDeadline(fn,{...options,timeoutMs:15})},MaterialBatchRuntime62:{poll:id=>calls.push(id)},updateMaterialIntegrityAudit47:task=>calls.push(task.task_id)};
  const api=async(url,opt={})=>{if(opt.method==='POST'){postCount++;throw new TypeError('lost response')}return latest};
  new Function('window','state','pid','materialIntegrityAuditProgressDialog47','activeMaterialIntegrityRoot47','api','localStorage','toast',block)(win,state,()=>project,()=>root,()=>root,api,{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},()=>{});
  await win.startMaterialIntegrityAudit47();assert.equal(postCount,1);assert.equal(calls.length,0);assert.match(box.textContent,/结果待确认/);assert.equal(retry.textContent,'查询审计提交结果');
  await win.startMaterialIntegrityAudit47();assert.equal(postCount,1);assert.equal(calls.length,0);
  latest={task:{task_id:'accepted-audit'}};
  await win.startMaterialIntegrityAudit47();assert.equal(postCount,1);assert.deepEqual(calls,['accepted-audit','accepted-audit']);assert.equal(storage.size,0);
});

test('pending create becomes persistent unknown and never posts again on query',()=>fixture(async({messages})=>{
  let posts=0;
  globalThis.fetch=async url=>{
    if(url.endsWith('/estimate'))return Response.json({supported:true,count:1,selection_spec:{scope:'CURRENT_PAGE'}});
    if(url.includes('?'))return Response.json({items:[]});
    posts++;return new Promise(()=>{});
  };
  await window.runMaterialBatch62('DELETE_INDEX',{scope:'CURRENT_PAGE'});
  await window.runMaterialBatch62('DELETE_INDEX',{scope:'CURRENT_PAGE'});
  assert.equal(posts,1);assert.match(messages.join(' '),/结果待确认/);
}));

test('audit baseline read failure never recovers an unrelated historical audit and permits retry',async()=>{
  const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
  const block=source.slice(source.indexOf('window.startMaterialIntegrityAudit47=async function(){'),source.indexOf('function materialIntegrityDuplicate47'));
  const storage=new Map(),state={},calls=[],box={},retry={},root={isConnected:true,dataset:{},querySelector:selector=>selector.includes('retry')?retry:box};
  let gets=0,posts=0;
  const win={PlatformCore:{withRequestDeadline},MaterialBatchRuntime62:{poll:id=>calls.push(id)},updateMaterialIntegrityAudit47:task=>calls.push(task.task_id)};
  const api=async(url,opt={})=>{if(opt.method==='POST'){posts++;return {task_id:'new-audit'}}if(++gets===1)throw new TypeError('baseline unavailable');return {task:{task_id:'old-audit'}}};
  new Function('window','state','pid','materialIntegrityAuditProgressDialog47','activeMaterialIntegrityRoot47','api','localStorage','toast',block)(win,state,()=> 'p1',()=>root,()=>root,api,{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},()=>{});
  await win.startMaterialIntegrityAudit47();
  assert.equal(posts,0);assert.deepEqual(calls,[]);assert.equal(storage.size,0);assert.match(box.textContent,/读取失败/);assert.doesNotMatch(box.textContent,/结果待确认/);
  await win.startMaterialIntegrityAudit47();assert.equal(posts,1);assert.deepEqual(calls,['new-audit','new-audit']);
});
