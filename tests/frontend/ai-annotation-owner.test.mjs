import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

test('final AI annotation owner uses durable v60 candidate review flow', () => {
  const legacyV33 = source.lastIndexOf('/api/v33/projects/${pid()}/prelabel-tasks');
  const legacyV35 = source.lastIndexOf('/api/v35/projects/${pid()}/prelabel-tasks');
  const finalSubmit = source.lastIndexOf('window.submitAiLabel429=async function(ids=[])');
  assert.ok(finalSubmit > legacyV33, 'final submit owner must load after v33 compatibility code');
  assert.ok(finalSubmit > legacyV35, 'final submit owner must load after v35 compatibility code');

  const submitEnd = source.indexOf('\n\n  function taskRow', finalSubmit);
  assert.ok(submitEnd > finalSubmit, 'final v60 submit block must remain bounded');
  const finalSubmitBody = source.slice(finalSubmit, submitEnd);
  assert.match(finalSubmitBody, /const task=await api\(taskApi\(\),/);
  assert.doesNotMatch(finalSubmitBody, /\/api\/v3[35]\/projects/);

  const finalPage = source.lastIndexOf('function renderAiTaskPage60');
  const finalRender = source.lastIndexOf('window.renderOps427=function()');
  const legacyRender = source.lastIndexOf('window.renderAutoLabel422=async function()');
  assert.ok(finalPage > legacyRender, 'v60 task shell must load after legacy auto-label pages');
  assert.ok(finalRender > finalPage, 'v60 task list must remain the final auto-label page owner');
  assert.match(source.slice(finalPage, finalRender), /AI自动标注/);
  assert.match(source.slice(finalRender), /候选结果不会自动写入正式标注/);
  assert.equal((source.match(/window\.showTaskProgress427=/g) || []).length, 1);
  assert.equal(source.includes('const showTaskBase429=window.showTaskProgress427;'), false);
  assert.equal(source.includes('const previousShowTask=window.showTaskProgress427;'), false);
  assert.match(source, /window\.showTaskProgressCore427=async function\(type,id\)/);
  assert.match(source, /window\.showCleanTaskProgress429=async function\(id\)/);
  assert.match(source, /window\.showTaskProgress427=function showTaskProgressCanonical60\(type,id\)/);
});

test('AI create dialog uses one canonical owner with explicit decorators', () => {
  assert.equal((source.match(/window\.createAiLabel429=/g) || []).length, 1);
  assert.equal((source.match(/window\.createAiLabel427=/g) || []).length, 1);
  assert.equal((source.match(/window\.aiRefSelect412=/g) || []).length, 1);
  for (const token of [
    'const baseCreateAi417=window.createAiLabel429;',
    'const baseCreateAi412=window.createAiLabel429;',
    'const baseSelectReference417=window.aiRefSelect412;',
  ]) assert.equal(source.includes(token), false, token);
  assert.match(source, /window\.createAiLabelCore429=function\(opts=\{\}\)/);
  assert.match(source, /window\.decorateAiReferenceLabels417=function\(\)/);
  assert.match(source, /window\.decorateAiReferenceBulk412=function\(\)/);
  assert.match(source, /window\.createAiLabel429=function createAiLabelCanonical429\(opts=\{\}\)/);
  assert.match(source, /window\.aiRefSelect412=function aiRefSelectCanonical412\(mode\)/);
});

test('final label management page owner is the alias-aware schema manager', () => {
  assert.match(source, /window\.manageLabels=\(\)=>\{closeModal\(\);setPage\('标签管理'\)\};/);
  assert.doesNotMatch(source, /state\.page==='标签管理'.*renderLabelManagement414/);
  assert.match(main, /\['标签管理', 'renderLabelManagement414'\]/);
  assert.match(main, /navigationStabilityRuntime\.registerPageOwner\(page/);
  assert.match(source, /id="label414Aliases"/);
  assert.match(source, /自动预选后仍需人工确认/);
});
test('AI review can explicitly create a canonical label but Ground Truth still commits through review mapping', () => {
  const reviewStart = source.lastIndexOf('function renderAiLabelMapping60()');
  const reviewEnd = source.indexOf('/* Persistent deployment tests:', reviewStart);
  assert.ok(reviewStart > 0 && reviewEnd > reviewStart);
  const review = source.slice(reviewStart, reviewEnd);
  assert.match(review, /openInlineLabelCreate414\('ai'/);
  assert.match(review, /const label_mapping=Object\.fromEntries/);
  assert.match(review, /\/decisions/);
  assert.doesNotMatch(review, /create_labels/);
  assert.match(source, /候选结果不会自动写入正式标注/);
});

