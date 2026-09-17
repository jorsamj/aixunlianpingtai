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

  const probe = liveOwner('window.testModelConfigV35=async function(id)', 3500);
  assertFenceBefore(probe, "modal('模型连接与标注解析测试'", 'testModelConfigV35');
});

test('final clean confirmation alias owner fences stale completion and stays local-state only', () => {
  const owner = liveOwner('window.confirmClean429=async function(id)', 4500);
  assertFenceBefore(owner, 'const del=', 'confirmClean429');
  assert.ok(owner.indexOf('closeModal()') > owner.indexOf('action&&!action.isCurrent()'), 'confirmClean429 must not close a new-page modal after navigation');
  assert.match(owner, /deleted_ids/, 'clean confirmation must patch local images from backend-confirmed deleted_ids');
  assert.match(owner, /processed_ids/, 'clean confirmation must preserve backend-confirmed processed_ids state patching');
  assert.doesNotMatch(owner, /await loadRelated\(\)/, 'final clean confirmation must not broad-refresh project state after mutation');
  assert.match(app, /window\.confirmClean427=window\.confirmClean429;/, 'legacy confirmClean427 entrypoint must delegate to the final confirmClean429 owner');
});

test('v60 review completion is the final AI commit owner and fences stale UI effects', () => {
  const taskApi = liveOwner("const taskApi=id=>`/api/v60/projects/${pid()}/annotation-tasks", 800);
  assert.match(taskApi, /annotation-tasks/, 'v60 taskApi must keep the durable annotation-task endpoint');

  const owner = liveOwner('window.completeAiReview60=async mode=>', 4200);
  assertFenceBefore(owner, 'applyTaskResult(result)', 'completeAiReview60');
  assert.ok(owner.indexOf('closeModal()') > owner.indexOf('action&&!action.isCurrent()'), 'completeAiReview60 must not close a new-page modal after navigation');
  assert.match(owner, /taskApi\(review\.id\)\}\/decisions/, 'v60 review completion must commit through the durable task decisions endpoint');
  assert.match(owner, /commit:true/, 'v60 review completion must preserve explicit commit semantics');
  assert.match(app, /window\.confirmAiLabel427=id=>completeAiReview60\('partial'\);/, 'legacy confirmAiLabel427 must remain only as a v60 compatibility alias');
});
