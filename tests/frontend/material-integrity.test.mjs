import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('material integrity stays inside material management and uses durable batch deletion', () => {
  assert.match(app, /重复与异常素材/);
  assert.match(app, /AUDIT_MATERIAL_INTEGRITY/);
  assert.match(app, /DUPLICATE_ANNOTATION_CONFLICT:'同图不同标注'/);
  assert.match(app, /同一图片存在不同 Ground Truth/);
  assert.match(app, /系统不会自动保留第一条/);
  assert.match(app, /runMaterialBatch62\?\.\('DELETE_INDEX'/);
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
