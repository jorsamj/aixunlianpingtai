import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

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
  assert.match(box.innerHTML,/成功 4/);
  assert.doesNotMatch(box.innerHTML,/尚未分配 Worker/);
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
