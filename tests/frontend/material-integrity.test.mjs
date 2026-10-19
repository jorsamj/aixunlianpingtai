import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('shared API preserves structured governance failure reason and code', async () => {
  const source=app.split('\n')[1];
  const context={FormData,fetch:async()=>new Response(JSON.stringify({detail:{code:'MATERIAL_INTEGRITY_PLAN_STALE',message:'标注已变化，请重新预检'}}),{status:409}),result:null};
  vm.createContext(context);
  vm.runInContext(source+';result=api("/api/test").catch(error=>({message:error.message,code:error.code}));',context);
  const error=await context.result;
  assert.match(error.message,/标注已变化，请重新预检/);
  assert.equal(error.code,'MATERIAL_INTEGRITY_PLAN_STALE');
  assert.doesNotMatch(error.message,/object Object/);
});

test('returning from governance surfaces failed recheck and keeps the current dialog',async()=>{
  const start=app.indexOf('window.returnMaterialIntegritySelection47=');
  const end=app.indexOf('window.invalidateMaterialIntegrityGovernance47=',start);
  const box={hidden:true,textContent:''},messages=[];
  const context={window:{},state:{materialIntegrityTrainingContext47:{projectId:'p',onReturn:async()=>{throw new Error('当前选择读取失败 HTTP503')}}},
    pid:()=> 'p',document:{getElementById:()=>box},toast:message=>messages.push(message)};
  vm.runInNewContext(app.slice(start,end),context);
  await context.window.returnMaterialIntegritySelection47();
  assert.equal(box.hidden,false);assert.match(box.textContent,/当前选择读取失败 HTTP503/);
  assert.deepEqual(messages,['当前选择读取失败 HTTP503']);
});

test('anomaly delete retains the selection modal and uses a frozen server preview', async () => {
  const start = app.indexOf('window.deleteMaterialIntegrity47=');
  const end = app.indexOf('window.deleteSelectedMaterialIntegrity47=', start);
  let closed = false, preview;
  const context = {window: {}, confirm: () => true, closeModal: () => {closed = true;},
    toast: () => {}, state: {},
  };
  context.window.previewMaterialIntegrityGovernance47 = async (scope, payload) => {preview = {scope, payload};};
  vm.runInNewContext(app.slice(start, end), context);
  await context.window.deleteMaterialIntegrity47(['image-a', 'image-a']);
  assert.equal(closed, false, 'preflight must not discard the original selection');
  assert.equal(preview.scope, 'SELECTED_IMAGES');
  assert.deepEqual(Array.from(preview.payload.imageIds), ['image-a']);
});

test('unknown image dimensions never produce an untrustworthy SVG', () => {
  const start = app.indexOf('function materialIntegrityOverlay47(');
  const end = app.indexOf('window.openMaterialIntegrityGroup47=', start);
  const context = {esc: String, window: {}};
  vm.createContext(context);
  vm.runInContext(app.slice(start, end), context);
  assert.equal(context.materialIntegrityOverlay47({boxes: [{x2: 10, y2: 10}]}), '');
  assert.match(context.materialIntegrityOverlay47({width: 160, height: 90, boxes: []}), /viewBox="0 0 160 90"/);
});

test('terminal task truth does not describe a cleared Worker lease as still waiting', () => {
  const start=app.indexOf('window.updateMaterialIntegrityTask47=');
  const end=app.indexOf('window.selectMaterialIntegrityGroups47=',start);
  const box={innerHTML:''},context={window:{},state:{},pid:()=> 'p',esc:String,document:{getElementById:()=>box}};
  vm.runInNewContext(app.slice(start,end),context);
  context.window.updateMaterialIntegrityTask47({task_id:'deleted',operation:'DELETE_INDEX',status:'PARTIAL_SUCCESS',total:5,processed:5,succeeded:4,failed:1,worker_id:null});
  assert.match(box.innerHTML,/部分成功/);
  assert.match(box.innerHTML,/实际删除索引 4/);
  assert.match(box.innerHTML,/执行节点未记录/);
  assert.doesNotMatch(box.innerHTML,/Worker 执行标识未返回/);
});

test('successful task status never fabricates 100 percent if counters disagree', () => {
  const start = app.indexOf('window.updateMaterialIntegrityTask47=');
  const end = app.indexOf('window.selectMaterialIntegrityGroups47=', start);
  const box = {innerHTML: ''};
  const context = {window: {}, state: {}, pid: () => 'p', esc: String, document: {getElementById: () => box}};
  vm.runInNewContext(app.slice(start, end), context);
  context.window.updateMaterialIntegrityTask47({
    task_id: 'inconsistent', operation: 'DELETE_INDEX', status: 'SUCCEEDED',
    total: 8, processed: 2, succeeded: 2, failed: 0, worker_id: null,
  });
  assert.match(box.innerHTML, /max="8" value="2"/);
  assert.match(box.innerHTML, /未处理 6/);
  assert.match(box.innerHTML, /任务成功状态与已处理数量不一致/);
  assert.doesNotMatch(box.innerHTML, /max="8" value="8"/);
});

test('material integrity stays inside material management and uses durable batch deletion', () => {
  assert.match(app, /重复与异常素材/);
  assert.match(app, /AUDIT_MATERIAL_INTEGRITY/);
  assert.match(app, /DUPLICATE_ANNOTATION_CONFLICT:'同图不同标注'/);
  assert.match(app, /同一图片存在不同 Ground Truth/);
  assert.match(app, /系统不会自动保留第一条/);
  // Integrity deletions now require the same frozen plan for anomalies and duplicates.
  assert.match(app, /previewMaterialIntegrityGovernance47\('SELECTED_IMAGES'/);
  assert.match(app, /dedup-plans\/\$\{encodeURIComponent\(planId\)\}\/execute/);
  assert.match(app, /共享物理对象不会被删除/);
});

test('material integrity provides overlay evidence and explicit human actions', () => {
  assert.match(app, /materialIntegrityOverlay47/);
  assert.match(app, /进入标注/);
  assert.match(app, /保留这条/);
  assert.match(app, /批量删除/);
  assert.match(app, /openAnnotation/);
});

test('material audit paginates all issue groups and visibly discloses scan failures', () => {
  assert.ok(app.includes('window.loadMoreMaterialIntegrityGroups47=async function'));
  assert.ok(app.includes("audit.nextCursor=page.next_cursor||''"));
  assert.ok(app.includes('materialIntegrityGroupList47'));
  assert.ok(app.includes('加载更多问题组'));
  assert.ok(app.includes('素材审计未完全核验'));
});

test('zero-deletion preview consolidates review links and issue rows remain paged', () => {
  const start=app.indexOf('function decorateIntegrityPlan47(plan)');
  const end=app.indexOf('window.previewMaterialIntegrityGovernance47=',start);
  const owner=app.slice(start,end);
  assert.ok(start>=0&&end>start);
  assert.match(owner,/返回待核对问题组/);
  assert.match(owner,/window\.returnMaterialIntegritySelection47/);
  assert.doesNotMatch(owner,/for\(const group of plan\.review_groups/);
  assert.match(app,/\/groups\?limit=25/);
});

test('global duplicate governance previews a server-frozen plan before durable execution', () => {
  assert.match(app, /previewMaterialIntegrityGovernance47/);
  assert.match(app, /\/dedup-plans/);
  assert.match(app, /previewMaterialIntegrityGovernance47\('SAFE_ALL'\)/);
  assert.match(app, /previewMaterialIntegrityGovernance47\('SELECTED_GROUPS'\)/);
  assert.match(app, /confirmation_credential/);
  assert.match(app, /executeMaterialIntegrityGovernance47/);
  assert.match(app, /MaterialBatchRuntime62\?\.poll\?\.\(task\.task_id\)/);
  assert.doesNotMatch(app, /dedup-plans[\s\S]{0,300}image_ids/);
});

test('annotation conflicts use an explicit keeper decision instead of direct bulk deletion', () => {
  const start = app.indexOf('window.keepMaterialIntegrity47=');
  const end = app.indexOf('const BATCH414_PAGE_SIZE', start);
  assert.ok(start >= 0 && end > start);
  const owner = app.slice(start, end);
  assert.match(owner, /previewMaterialIntegrityGovernance47\('MANUAL_GROUPS'/);
  assert.match(owner, /manualDecisions/);
  assert.doesNotMatch(owner, /runMaterialBatch62/);
});


test('GT review uses only visible modal ownership, offers explicit discard and asynchronous status', () => {
  assert.match(app, /function activeMaterialIntegrityRoot47\(selector\)/);
  assert.match(app, /activeMaterialIntegrityRoot47\('\.gt-review-workbench'\)/);
  assert.match(app, /data-gt-review-discard-selected/);
  assert.match(app, /data-gt-review-discard-all/);
  assert.match(app, /data-gt-review-progress/);
  assert.match(app, /confirm_discard_conflicts:true/);
  assert.match(app, /scope='DISCARD_CONFLICTS'|previewMaterialIntegrityGovernance47\('DISCARD_CONFLICTS'/);
  assert.match(app, /groupKeys:keys/);
});

test('audit acceptance leaves visible progress and uses existing material batch polling owner', () => {
  assert.match(app, /materialIntegrityAuditProgressDialog47/);
  assert.match(app, /window.updateMaterialIntegrityAudit47=function\(task\)/);
  assert.match(app, /id="materialIntegrityAuditProgress47"/);
  assert.match(app, /data-integrity-audit-open/);
  assert.doesNotMatch(app.slice(app.indexOf('window.startMaterialIntegrityAudit47='), app.indexOf('function materialIntegrityDuplicate47')), /closeModal\(\)/);
});

test('asynchronous material integrity actions are owned by the current visible modal', () => {
  const group=app.slice(app.indexOf('window.openMaterialIntegrityGroup47='),app.indexOf('function updateMaterialIntegritySelection47()'));
  assert.match(group,/const loading=activeMaterialIntegrityRoot47/);
  assert.match(group,/if\(!current\(\)\)return/);
  const audit=app.slice(app.indexOf('window.openMaterialIntegrityAudit47='),app.indexOf('async function loadMaterialIntegrityClassification47'));
  assert.match(audit,/const current=\(\)=>pid\(\)===projectAtStart/);
  assert.match(audit,/if\(!current\(\)\)return/);
  const groups=app.slice(app.indexOf('window.loadMoreMaterialIntegrityGroups47='),app.indexOf('window.openMaterialIntegrityAudit47='));
  assert.match(groups,/!list\.isConnected/);
  const images=app.slice(app.indexOf('window.loadMoreMaterialIntegrityItems47='),app.indexOf('window.toggleMaterialIntegrity47='));
  assert.match(images,/!grid\.isConnected/);
});

test('audit progress without a numeric backend value stays indeterminate', () => {
  const progress=app.slice(app.indexOf('window.updateMaterialIntegrityAudit47='),app.indexOf('window.startMaterialIntegrityAudit47='));
  assert.match(progress,/task\.progress_percent==null\?NaN/);
  assert.match(progress,/progress\.removeAttribute\('value'\)/);
});
