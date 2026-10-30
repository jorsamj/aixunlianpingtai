import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function liveOwner(marker, size = 7000) {
  const index = app.lastIndexOf(marker);
  assert.ok(index >= 0, `live owner not found: ${marker}`);
  return app.slice(index, index + size);
}

function assertFenceBefore(owner, beforeMarker, label) {
  const capture = owner.indexOf('NavigationStability?.action?.(state.page)');
  const stale = owner.indexOf('action&&!action.isCurrent()');
  const before = owner.indexOf(beforeMarker);
  assert.ok(capture >= 0, `${label} must capture NavigationStability action fence`);
  assert.ok(stale > capture, `${label} must reject stale completion`);
  assert.ok(before > stale, `${label} stale check must occur before ${beforeMarker}`);
}

test('final M4 model save and connection test fence stale modal effects', () => {
  const save = liveOwner("window.saveVisionModelM4=async function(id='')", 6500);
  assertFenceBefore(save, 'if(saved?.id)', 'saveVisionModelM4');
  assert.ok(save.indexOf('closeModal()') > save.indexOf('action&&!action.isCurrent()'), 'saveVisionModelM4 must not close a new-page modal after navigation');

  const probe = liveOwner('window.testModelConfigM4=async function(id)', 3500);
  assertFenceBefore(probe, "modal('模型连接与标注解析测试'", 'testModelConfigV35');
});

test('final clean confirmation alias owner fences stale completion and stays local-state only', () => {
  const owner = liveOwner('window.confirmClean429=async function(id)', 4500);
  assertFenceBefore(owner, 'const proc=', 'confirmClean429');
  assert.ok(owner.indexOf('closeModal()') > owner.indexOf('action&&!action.isCurrent()'), 'confirmClean429 must not close a new-page modal after navigation');
  assert.match(owner, /runMaterialBatch62\('DELETE_INDEX'/, 'clean deletion must use the existing durable preview owner');
  assert.match(owner, /delete_ids:\[\],skip_image_ids:requested/, 'queued deletion candidates must not be acknowledged as processed');
  assert.match(owner, /processed_ids/, 'clean confirmation must preserve backend-confirmed processed_ids state patching');
  assert.doesNotMatch(owner, /await loadRelated\(\)/, 'final clean confirmation must not broad-refresh project state after mutation');
  assert.match(app, /window\.confirmClean427=window\.confirmClean429;/, 'legacy confirmClean427 entrypoint must delegate to the final confirmClean429 owner');
});

test('v60 review completion is the final AI commit owner and fences stale UI effects', () => {
  const taskApi = liveOwner("const taskApi=id=>`/api/v60/projects/${pid()}/annotation-tasks", 800);
  assert.match(taskApi, /annotation-tasks/, 'v60 taskApi must keep the durable annotation-task endpoint');

  const owner = liveOwner('window.completeAiReview60=async mode=>', 4200);
  const finisher = app.slice(app.lastIndexOf('async function finishAiReview60('), app.lastIndexOf('async function aiReviewLookupReceipt60('));
  assert.match(owner, /NavigationStability\?\.action\?\.\(state\.page\)/, 'review submission must capture the navigation action');
  assert.ok(finisher.indexOf('action&&!action.isCurrent()')>=0, 'shared review receipt handler must fence stale state');
  assert.ok(finisher.indexOf('applyTaskResult(result)') > finisher.indexOf('action&&!action.isCurrent()'), 'review completion must fence stale task patching');
  assert.ok(finisher.indexOf('window.closeAiReview60?.()') > finisher.indexOf('action&&!action.isCurrent()'), 'review completion must not close a newer review');
  assert.match(owner, /finishAiReview60\(review,result,mode,ownerPage,action\)/);
  assert.match(owner, /taskApi\(review\.id\)\}\/decisions/, 'v60 review completion must commit through the durable task decisions endpoint');
  assert.match(owner, /commit:true/, 'v60 review completion must preserve explicit commit semantics');
  assert.match(app, /window\.confirmAiLabel427=id=>completeAiReview60\('partial'\);/, 'legacy confirmAiLabel427 must remain only as a v60 compatibility alias');
});

test('clean confirmation queues previewed deletion and never marks those pending IDs as processed',async()=>{
  const source=app.slice(app.indexOf('  window.confirmClean429=async function(id){'),app.indexOf('\n  window.confirmClean427=window.confirmClean429;'));
  const calls=[],messages=[],modal={isConnected:true},button={disabled:false,isConnected:true,classList:{add(){},remove(){}}};
  const state={page:'数据集',v427CleanConfirm:new Set(['pending']),images:[{id:'pending'},{id:'clean'}]};
  const window={event:{currentTarget:button},PlatformCore:{withRequestDeadline:fn=>fn()},runMaterialBatch62:async(op,options)=>{calls.push({op,options});return {task_id:'delete-one'}}};
  let closed=0;
  new Function('window','state','pid','document','api','closeModal','renderDatasets424','toast',source)(window,state,()=> 'p',{querySelectorAll:()=>[modal]},async(url,options)=>{calls.push(JSON.parse(options.body));return {processed_ids:['clean']}},()=>closed++,()=>{},message=>messages.push(message));
  await window.confirmClean429('clean-task');
  assert.equal(calls[0].op,'DELETE_INDEX');assert.deepEqual(calls[1],{delete_ids:[],skip_image_ids:['pending']});
  assert.equal(state.images[0].processing_status,undefined);assert.equal(state.images[1].processing_status,'processed');assert.equal(closed,1);assert.equal(button.disabled,false);assert.match(messages[0],/按真实任务结果更新/);
});

test('cancelled delete preview leaves the clean confirmation open and sends no clean mutation',async()=>{
  const source=app.slice(app.indexOf('  window.confirmClean429=async function(id){'),app.indexOf('\n  window.confirmClean427=window.confirmClean429;'));
  let mutations=0,closed=0;
  const window={PlatformCore:{withRequestDeadline:fn=>fn()},runMaterialBatch62:async()=>null};
  new Function('window','state','pid','document','api','closeModal','renderDatasets424','toast',source)(window,{page:'数据集',v427CleanConfirm:new Set(['pending'])},()=> 'p',{querySelectorAll:()=>[]},async()=>{mutations++},()=>closed++,()=>{},()=>{});
  await window.confirmClean429('clean-task');assert.equal(mutations,0);assert.equal(closed,0);
});

test('late integrity execute response calls only the original training context',async()=>{
  const start=app.indexOf('  window.executeMaterialIntegrityGovernance47=async function(planId,credential){');
  const source=app.slice(start,app.indexOf('\n  function showMaterialIntegrityTask47',start));
  const view={isConnected:true},modal={isConnected:true,querySelector:()=>({firstElementChild:view})};
  const button={closest:()=>modal},calls=[];
  const original={onCreated:task=>calls.push(['original',task.task_id])};
  const state={materialIntegrityAudit47:{projectId:'p',task:{task_id:'audit'}},materialIntegrityPlan47:{plan_id:'plan'},materialIntegrityTrainingContext47:original};
  let release;
  const gate=new Promise(resolve=>{release=resolve});
  const window={};
  new Function('window','state','pid','document','activeMaterialIntegrityRoot47','api','toast','showMaterialIntegrityTask47',source)(window,state,()=> 'p',{querySelectorAll:()=>[modal]},()=>button,()=>gate,()=>{},()=>{});
  const pending=window.executeMaterialIntegrityGovernance47('plan','credential');
  state.materialIntegrityTrainingContext47={onCreated:task=>calls.push(['replacement',task.task_id])};
  state.materialIntegrityPlan47={plan_id:'replacement'};
  release({task_id:'old-deletion'});
  await pending;
  assert.deepEqual(calls,[['original','old-deletion']]);
});
