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
  assert.match(source, /window\.createAiLabel429=async function createAiLabelCanonical429\(opts=\{\}\)/);
  assert.match(source, /MaterialPaginationRuntime61\?\.ensureFullPool\?\.\(\)/);
  assert.match(source, /window\.aiRefSelect412=function aiRefSelectCanonical412\(mode\)/);
});

test('final label management page owner is the alias-aware schema manager', () => {
  assert.match(source, /window\.manageLabels=\(\)=>\{closeModal\(\);setPage\('标签管理'\)\};/);
  assert.doesNotMatch(source, /state\.page==='标签管理'.*renderLabelManagement414/);
  assert.match(main, /\['标签管理', 'renderLabelManagement414'\]/);
  assert.match(main, /navigationStabilityRuntime\.registerPageOwner\(page/);
  assert.match(source, /id="label414Aliases"/);
  assert.match(source, /不会用于导入时自动选择或推荐平台标签/);
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



test('retired AI submit compatibility entrypoint delegates to the v60 owner', () => {
  const marker = source.lastIndexOf('Persistent v60 AI annotation UI');
  const end = source.indexOf('/* Explicit canonical-label creation used by import/rescan/ZIP/AI confirmation.', marker);
  const finalLayer = source.slice(marker, end);
  assert.match(finalLayer, /window\.submitAiLabel427=\(ids=\[\]\)=>window\.submitAiLabel429\(ids\)/);
  assert.doesNotMatch(finalLayer, /\/api\/v47\/projects\/.*ai-label-tasks/);
  assert.match(finalLayer, /const task=await api\(taskApi\(\),/);
});


test('retired v47 AI review clients are absent from the production frontend', () => {
  assert.doesNotMatch(source, /\/api\/v47\/projects\/\$\{pid\(\)\}\/ai-label-tasks/);
  for (const token of [
    'reviewAiLabelLegacy427',
    'confirmAiLabelLegacy4271',
    'submitAiLabelLegacy429_1',
    'confirmAiLabelLegacy4272',
    'reviewAiLabelM4',
    '__m4ReviewCandidates',
    'candidateBoxM4',
    'toggleAiConfirm427',
    'v427AiConfirm',
  ]) assert.equal(source.includes(token), false, token);
  assert.match(source, /window\.submitAiLabel427=\(ids=\[\]\)=>window\.submitAiLabel429\(ids\)/);
  assert.match(source, /window\.reviewAiLabel427=async function\(id\)/);
  assert.match(source, /window\.confirmAiLabel427=id=>completeAiReview60\('partial'\)/);
});


test('AI task creation never resolves display names or aliases into canonical labels', () => {
  const helperStart = source.lastIndexOf('function explicitCanonicalAiLabelText(value)');
  const submitStart = source.lastIndexOf('window.submitAiLabel429=async function(ids=[])');
  assert.ok(helperStart > 0 && submitStart > helperStart);
  const helper = source.slice(helperStart, submitStart);
  assert.match(helper, /label\?\.code/);
  assert.match(helper, /const unknown=parts\.filter\(value=>!allowed\.has\(value\)\)/);
  assert.doesNotMatch(helper, /display_name|aliases|alias/);
  const submitEnd = source.indexOf('\n\n  function taskRow', submitStart);
  const submit = source.slice(submitStart, submitEnd);
  assert.match(submit, /labels_text:parsed\.text/);
  assert.match(submit, /只接受当前有效的平台标签 code/);
  assert.match(source, /中文名、别名、历史 alias 不会自动转换/);
  assert.doesNotMatch(source, /function normalizedLabelText\(/);
});


test('AI task detail polling is modal-scoped and PollRegistry-owned', () => {
  const start = source.lastIndexOf('function stopAiTaskDetail60');
  const end = source.indexOf('function explicitCanonicalAiLabelText', start);
  assert.ok(start > 0 && end > start);
  const block = source.slice(start, end);
  assert.match(block, /ai-task-detail:/);
  assert.match(block, /waitForTaskTerminal/);
  assert.match(block, /registry:window\.PollRegistryRuntime/);
  assert.match(block, /beforeCloseAiTask60/);
  assert.match(block, /AutoLabelPollRuntime\?\.deactivate/);
  assert.match(block, /AutoLabelPollRuntime\?\.activate/);
  assert.doesNotMatch(block, /createTaskPoller/);
  assert.doesNotMatch(source, /state\.ai60Pollers/);
  assert.match(source, /beforeCloseAiTask60\?\.\(top\)/);
  assert.match(source, /ai60Bar" style="transform:scaleX\(0\)/);
  assert.doesNotMatch(block, /bar\.style\.width=.*view\.percent/);
  const rowStart = source.indexOf('function taskRow(task)', end);
  const rowEnd = source.indexOf('function renderAiTaskRows60', rowStart);
  const rowBlock = source.slice(rowStart, rowEnd);
  assert.match(rowBlock, /transform:scaleX/);
  assert.doesNotMatch(rowBlock, /style="width:/);
});
